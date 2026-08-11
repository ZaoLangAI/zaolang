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

from app.agents.slots import DEFAULT_SLOT
from app.domain.agent_skills import service as agent_skills_service
from app.llm import client as llm_client
from app.models import AgentProfile, AgentRun
from app.models.base import utcnow
from app.models.enums import AgentName, AgentRunStatus
from app.observability.context import get_request_id
from app.platform_config import service as config_service
from app.platform_config.schemas import AgentConfig, AgentModelBinding, LlmProviderConfig

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class AgentOutcome:
    data: dict[str, Any]
    raw_text: str
    degraded: bool
    model: str
    agent_run_id: str


def resolve_binding(session: Session, agent_name: str) -> AgentModelBinding:
    """The config-centre model binding for a role.

    `AgentConfig` only guarantees an entry for the five built-in
    `AgentName` roles. A role created later from a preset falls back to the
    intent router's binding — the cheapest general-purpose one — which is
    only ever the starting point: such a role is expected to pin its own
    endpoint on the agent, and `effective_binding` layers that on top.
    """
    config = config_service.get_typed(session, "agents", AgentConfig)
    binding = config.bindings.get(agent_name)
    if binding is not None:
        return binding
    logger.info(
        "role %s has no entry in the agents config; using the intent_router binding as its base",
        agent_name,
    )
    return config.bindings[AgentName.INTENT_ROUTER.value]


@dataclass(slots=True, frozen=True)
class EffectiveBinding:
    """What one turn actually runs with, after an agent's own overrides."""

    model: str
    max_tokens: int
    temperature: float
    reasoning_model: bool
    # Endpoints this agent pinned, most preferred first. Empty means the
    # shared `kind="general"` pool in its usual failover order.
    preferred_endpoint_ids: tuple[str, ...] = ()


def effective_binding(
    session: Session, agent_name: str, profile: AgentProfile | None
) -> EffectiveBinding:
    """Layers an agent's own model binding over the role's config default.

    An agent that pins nothing behaves exactly as before: the config
    centre's binding, dispatched across the shared endpoint pool. An agent
    that pins `default_endpoint_id` gets that endpoint first and its
    `backup_endpoint_id` next, and — because an endpoint carries its own
    model list — is run against a model that endpoint actually serves rather
    than whatever the role-wide binding happens to name.
    """
    base = resolve_binding(session, agent_name)
    if profile is None or not profile.default_endpoint_id:
        return EffectiveBinding(
            model=base.model,
            max_tokens=profile.max_tokens if profile and profile.max_tokens else base.max_tokens,
            temperature=_temperature(profile, base),
            reasoning_model=_reasoning(profile, base),
        )

    endpoints = config_service.get_typed(session, "llm_providers", LlmProviderConfig).endpoints
    preferred = tuple(
        endpoint_id
        for endpoint_id in (profile.default_endpoint_id, profile.backup_endpoint_id)
        if endpoint_id and endpoint_id in endpoints
    )
    pinned = endpoints.get(profile.default_endpoint_id)
    model = base.model
    if pinned is not None and pinned.models and base.model not in pinned.models:
        model = pinned.models[0]

    return EffectiveBinding(
        model=model,
        max_tokens=profile.max_tokens or base.max_tokens,
        temperature=_temperature(profile, base),
        reasoning_model=_reasoning(profile, base),
        preferred_endpoint_ids=preferred,
    )


def _temperature(profile: AgentProfile | None, base: AgentModelBinding) -> float:
    if profile is None or profile.temperature_milli is None:
        return base.temperature
    return profile.temperature_milli / 1000


def _reasoning(profile: AgentProfile | None, base: AgentModelBinding) -> bool:
    if profile is None or profile.reasoning_model is None:
        return base.reasoning_model
    return profile.reasoning_model


def run_agent(
    session: Session,
    *,
    agent_name: str,
    system_prompt: str,
    user_prompt: str,
    fallback: dict[str, Any],
    job_id: str | None = None,
    user_id: str | None = None,
    agent_id: str | None = None,
    slot: str = DEFAULT_SLOT,
) -> AgentOutcome:
    """Runs one agent turn and always returns usable structured data.

    `fallback` is what the caller gets when the model produces nothing
    parseable. Callers must choose a fallback that is safe by default — for the
    safety agent that means "needs human review", never "approve".

    `system_prompt` is each agent module's own hardcoded constant. It is used
    verbatim only until an operator publishes an `AgentSkill` for this node;
    from then on the published prompt wins, without a code change or deploy.

    `agent_id` is the agent a workflow node bound (`None` for every caller
    outside the graph, which gets the role's default), and `slot` picks
    between the several system prompts one role may own — a role with two
    prompts must never resolve them by role alone.
    """
    resolved = agent_skills_service.resolve_prompt(
        session, agent_name, system_prompt, agent_id=agent_id, slot=slot
    )
    profile = resolved.profile
    profile_id = profile.id if profile is not None else None
    binding = effective_binding(session, agent_name, profile)
    result = llm_client.complete(
        session=session,
        agent_name=agent_name,
        model=binding.model,
        messages=[
            {"role": "system", "content": resolved.text},
            {"role": "user", "content": user_prompt},
        ],
        max_tokens=binding.max_tokens,
        temperature=binding.temperature,
        expect_json=True,
        reasoning_model=binding.reasoning_model,
        preferred_endpoint_ids=binding.preferred_endpoint_ids,
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
        agent_profile_id=profile_id,
        prompt_slot=slot,
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
