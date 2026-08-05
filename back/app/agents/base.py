"""Agent execution wrapper.

Every agent call goes through `run_agent`, which resolves the model binding
from the config centre, calls the gateway, and records an `AgentRun`. Nothing
an agent returns is a fact until a caller persists it through a domain service.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.domain.agent_skills import service as agent_skills_service
from app.llm import client as llm_client
from app.models import AgentRun
from app.models.base import utcnow
from app.models.enums import AgentRunStatus
from app.observability.context import get_request_id
from app.platform_config import service as config_service
from app.platform_config.schemas import AgentConfig, AgentModelBinding

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class AgentOutcome:
    data: dict[str, Any]
    raw_text: str
    degraded: bool
    model: str
    agent_run_id: str


def resolve_binding(session: Session, agent_name: str) -> AgentModelBinding:
    config = config_service.get_typed(session, "agents", AgentConfig)
    return config.bindings[agent_name]


def run_agent(
    session: Session,
    *,
    agent_name: str,
    system_prompt: str,
    user_prompt: str,
    fallback: dict[str, Any],
    job_id: str | None = None,
    user_id: str | None = None,
) -> AgentOutcome:
    """Runs one agent turn and always returns usable structured data.

    `fallback` is what the caller gets when the model produces nothing
    parseable. Callers must choose a fallback that is safe by default — for the
    safety agent that means "needs human review", never "approve".

    `system_prompt` is each agent module's own hardcoded constant. It is used
    verbatim only until an operator publishes an `AgentSkill` for this node;
    from then on the published prompt wins, without a code change or deploy.
    """
    binding = resolve_binding(session, agent_name)
    effective_prompt = agent_skills_service.get_active_prompt(session, agent_name, system_prompt)
    result = llm_client.complete(
        session=session,
        agent_name=agent_name,
        model=binding.model,
        messages=[
            {"role": "system", "content": effective_prompt},
            {"role": "user", "content": user_prompt},
        ],
        max_tokens=binding.max_tokens,
        temperature=binding.temperature,
        expect_json=True,
        reasoning_model=binding.reasoning_model,
    )

    parse_failed = result.response.data is None
    if result.response.data is None:
        logger.warning("agent %s returned unparseable output; using fallback", agent_name)
        data = dict(fallback)
    else:
        data = result.response.data

    status = AgentRunStatus.SUCCEEDED
    if result.degraded:
        status = AgentRunStatus.DEGRADED
    elif parse_failed:
        status = AgentRunStatus.FAILED

    run = AgentRun(
        job_id=job_id,
        user_id=user_id,
        agent_name=agent_name,
        mode=result.mode,
        model=result.response.model or binding.model,
        status=status,
        degraded=result.degraded or parse_failed,
        degrade_reason=result.degrade_reason or ("json_parse_failed" if parse_failed else None),
        prompt_tokens=result.response.prompt_tokens,
        completion_tokens=result.response.completion_tokens,
        latency_ms=result.latency_ms,
        endpoint_id=result.endpoint_id,
        output_json=data,
        request_id=get_request_id() or None,
        created_at=utcnow(),
    )
    session.add(run)
    session.flush()

    return AgentOutcome(
        data=data,
        raw_text=result.response.text,
        degraded=run.degraded,
        model=run.model or binding.model,
        agent_run_id=run.id,
    )


# Models that reject `response_format` still need to be told to emit JSON, so
# every system prompt carries the instruction explicitly.
JSON_INSTRUCTION = "只输出一个 JSON 对象，不要输出任何解释、前言或 Markdown 代码块标记。"
