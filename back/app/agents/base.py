"""Agent execution wrapper.

Every agent call goes through `run_agent`, which resolves its AgentProfile
provider/model binding, calls the gateway, and records an `AgentRun`. Nothing
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
from app.llm.model_defaults import DEFAULT_MAX_TOKENS, DEFAULT_TEMPERATURE
from app.models import AgentProfile, AgentRun
from app.models.base import utcnow
from app.models.enums import AgentRunStatus
from app.observability.context import get_request_id
from app.platform_config import service as config_service
from app.platform_config.schemas import LlmProviderConfig

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class AgentOutcome:
    data: dict[str, Any]
    raw_text: str
    degraded: bool
    model: str
    agent_run_id: str


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
    """Resolves provider/model selection from AgentProfile.

    Non-default profiles inherit empty values from the role's default profile.
    The model id is only whatever an administrator stored on the profile —
    never a code-level default name. A pin that drifted off the catalog is
    treated as unbound rather than guessed.
    """
    role_default = agent_skills_service.default_profile(session, agent_name)
    inherited = (
        role_default
        if role_default is not None and (profile is None or role_default.id != profile.id)
        else None
    )

    def value(name: str) -> Any:
        own = getattr(profile, name, None) if profile is not None else None
        return own if own is not None and own != "" else getattr(inherited, name, None)

    endpoints = config_service.get_typed(session, "llm_providers", LlmProviderConfig).endpoints
    default_endpoint_id = value("default_endpoint_id")
    backup_endpoint_id = value("backup_endpoint_id")
    preferred = tuple(
        endpoint_id for endpoint_id in (default_endpoint_id, backup_endpoint_id) if endpoint_id
    )
    model = value("model") or ""
    pinned = endpoints.get(default_endpoint_id) if default_endpoint_id else None
    if pinned is not None and model and model not in pinned.models:
        model = ""

    return EffectiveBinding(
        model=model,
        max_tokens=value("max_tokens") or DEFAULT_MAX_TOKENS,
        temperature=(
            value("temperature_milli") / 1000
            if value("temperature_milli") is not None
            else DEFAULT_TEMPERATURE
        ),
        reasoning_model=bool(value("reasoning_model")),
        preferred_endpoint_ids=preferred,
    )


def _recorded_model(result: llm_client.LlmCallResult, binding: EffectiveBinding) -> str | None:
    """Persists the catalog model that ran, or nothing when none was bound."""
    if result.degrade_reason == llm_client.NO_MODEL_BOUND:
        return None
    return result.response.model or binding.model or None


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
        model=binding.model or "",
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
        model=_recorded_model(result, binding),
        status=status,
        degraded=result.degraded or parse_failed,
        degrade_reason=result.degrade_reason or ("json_parse_failed" if parse_failed else None),
        prompt_tokens=result.response.prompt_tokens,
        completion_tokens=result.response.completion_tokens,
        latency_ms=result.latency_ms,
        endpoint_id=result.endpoint_id,
        input_json={"system_prompt": resolved.text, "user_prompt": user_prompt},
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
        model=run.model or binding.model or "",
        agent_run_id=run.id,
    )


@dataclass(slots=True)
class DebugChatOutcome:
    reply_text: str
    parsed_json: dict[str, Any] | None
    degraded: bool
    model: str
    latency_ms: int
    prompt_tokens: int | None
    completion_tokens: int | None
    agent_run_id: str


def run_agent_debug(
    session: Session,
    *,
    profile: AgentProfile,
    slot: str,
    prompt_override: str | None,
    history: list[dict[str, str]],
) -> DebugChatOutcome:
    """Runs one turn of prompt-evaluation chat against a real model, with no
    job behind it.

    Mirrors the workflow sandbox-run's own precedent
    (`workflow_templates_service` + its `sandbox-run` endpoint): a draft
    prompt can be tried before it is ever published, the call is real (never
    stubbed unless `LLM_MODE=stub`), and an `AgentRun` is written with
    `job_id=None` so the "agent invocations" console list still shows what a
    debug session cost — unlike a sandbox job, this debug path still has no
    `GenerationJob` behind it.

    `prompt_override` is the skill editor's unsaved draft when given;
    otherwise this resolves whatever is currently active for
    `(profile, slot)`, falling back through the role's default agent exactly
    as a live run would (`resolve_prompt`). The empty-string floor at the
    end of that chain only bites a role nobody has ever published anything
    for — a clearly-empty reply here is the right way to surface that during
    debugging, where `run_agent`'s callers instead have their own hardcoded
    constant to fall back to.
    """
    if prompt_override is not None:
        system_prompt = prompt_override
    else:
        resolved = agent_skills_service.resolve_prompt(
            session, profile.role, "", agent_id=profile.id, slot=slot
        )
        system_prompt = resolved.text

    binding = effective_binding(session, profile.role, profile)
    result = llm_client.complete(
        session=session,
        agent_name=profile.role,
        model=binding.model,
        messages=[{"role": "system", "content": system_prompt}, *history],
        max_tokens=binding.max_tokens,
        temperature=binding.temperature,
        expect_json=True,
        reasoning_model=binding.reasoning_model,
        preferred_endpoint_ids=binding.preferred_endpoint_ids,
    )

    run = AgentRun(
        job_id=None,
        user_id=None,
        agent_name=profile.role,
        agent_profile_id=profile.id,
        prompt_slot=slot,
        mode=result.mode,
        model=_recorded_model(result, binding),
        status=AgentRunStatus.DEGRADED if result.degraded else AgentRunStatus.SUCCEEDED,
        degraded=result.degraded,
        degrade_reason=result.degrade_reason,
        prompt_tokens=result.response.prompt_tokens,
        completion_tokens=result.response.completion_tokens,
        latency_ms=result.latency_ms,
        endpoint_id=result.endpoint_id,
        input_json={
            "system_prompt": system_prompt,
            "user_prompt": history[-1]["content"] if history else "",
        },
        output_json=result.response.data or {},
        request_id=get_request_id() or None,
        created_at=utcnow(),
    )
    session.add(run)
    session.flush()

    return DebugChatOutcome(
        reply_text=result.response.text,
        parsed_json=result.response.data,
        degraded=result.degraded,
        model=run.model or binding.model or "",
        latency_ms=result.latency_ms,
        prompt_tokens=result.response.prompt_tokens,
        completion_tokens=result.response.completion_tokens,
        agent_run_id=run.id,
    )


# Models that reject `response_format` still need to be told to emit JSON, so
# every system prompt carries the instruction explicitly.
JSON_INSTRUCTION = "只输出一个 JSON 对象，不要输出任何解释、前言或 Markdown 代码块标记。"
