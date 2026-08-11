"""Versioned agent prompts, append-only like `platform_config.service`.

Publishing never overwrites a row: it appends a new version and flips the
active flag inside one transaction, so any earlier prompt can be replayed by
re-publishing its content as the newest version. There is deliberately no
`update()` — editing a live prompt in place would erase the ability to explain
why a generation behaved the way it did.

Prompts hang off an `(agent, slot)` pair rather than off the role directly:

* an **agent** (`AgentProfile`) has a role, and a role may have several
  agents, so `text_to_video` can bind a stricter safety agent than
  `text_to_image` without either workflow having to fork the agent code;
* a **slot** separates the several system prompts one role may own (see
  `app.agents.slots`).

Resolution is deliberately forgiving at runtime — bound agent, then the
role's default agent, then the calling module's own constant. A missing
agent must degrade to a working prompt, never to an empty one; publish-time
validation is where a typo gets caught (`workflow_templates.service`).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.agents.slots import DEFAULT_SLOT, is_known_slot
from app.domain.agent_skills import presets
from app.domain.errors import NotFound, ValidationFailed
from app.models import AgentNode, AgentProfile, AgentSkill
from app.models.base import utcnow
from app.models.enums import Operation
from app.platform_config import service as config_service
from app.platform_config.schemas import LlmProviderConfig, LlmProviderEndpoint

logger = logging.getLogger(__name__)

DEFAULT_PROFILE_KEY = "default"

# The judgment roles the shipped pipeline invokes by name. Creative presets are
# deliberately not seeded: their node row is created the first time an operator
# actually builds an agent for one, so an untouched install shows exactly the
# five stages its workflow templates reference.
DEFAULT_NODES: list[dict[str, Any]] = [
    {
        "role": "safety",
        "display_name": "安全审核",
        "description": "内容安全一票否决",
        "sort_order": 0,
    },
    {
        "role": "planner",
        "display_name": "任务规划",
        "description": "把意图拆解为生成计划",
        "sort_order": 1,
    },
    {
        "role": "quality",
        "display_name": "质量评估",
        "description": "评估生成结果是否达标",
        "sort_order": 2,
    },
    {
        "role": "copy",
        "display_name": "文案生成",
        "description": "生成标题与文案",
        "sort_order": 3,
    },
    {
        "role": "intent_router",
        "display_name": "意图理解路由",
        "description": "判断需求复杂度，建议更省成本的生成档位（只能降级，不参与计费）",
        "sort_order": 4,
    },
]

_VALID_OPERATIONS = {op.value for op in Operation}

# A creative agent's cost preference per media candidate. Deliberately a plain
# relative number with a neutral midpoint rather than a percentage: it is
# context handed to the routing agent, not a share of anything, and nothing in
# `app/agents/router.py` computes with it.
MIN_CANDIDATE_WEIGHT = 1
MAX_CANDIDATE_WEIGHT = 1_000
DEFAULT_CANDIDATE_WEIGHT = 100


# --------------------------------------------------------------------------
# Nodes (roles)
# --------------------------------------------------------------------------


def find_node(session: Session, role: str) -> AgentNode | None:
    return session.scalar(select(AgentNode).where(AgentNode.role == role))


def ensure_node_for_role(session: Session, role: str) -> AgentNode:
    """The `AgentNode` for one preset role, created on first use.

    New roles are not free text: only a preset in
    `app.domain.agent_skills.presets` can become a node, because a role no
    code path invokes would produce an agent that can never run. An existing
    row is returned as-is even if its role has since left the catalogue —
    dropping a preset must not make the agents already built on it
    unreachable.
    """
    existing = find_node(session, role)
    if existing is not None:
        return existing

    preset = presets.find(role)
    if preset is None:
        raise ValidationFailed(f"未知的智能体角色: {role}")

    row = AgentNode(
        role=preset.role,
        display_name=preset.display_name,
        description=preset.description,
        category=preset.category,
        enabled=True,
        sort_order=preset.sort_order,
    )
    session.add(row)
    session.flush()
    return row


# --------------------------------------------------------------------------
# Profiles
# --------------------------------------------------------------------------


def list_profiles(session: Session, *, role: str | None = None) -> list[AgentProfile]:
    stmt = select(AgentProfile).order_by(
        AgentProfile.role, AgentProfile.is_default.desc(), AgentProfile.key
    )
    if role is not None:
        stmt = stmt.where(AgentProfile.role == role)
    return list(session.scalars(stmt))


def get_profile(session: Session, profile_id: str) -> AgentProfile:
    row = session.get(AgentProfile, profile_id)
    if row is None:
        raise NotFound(f"智能体 {profile_id} 不存在。")
    return row


def find_agent(session: Session, agent_id: str) -> AgentProfile | None:
    """The agent a workflow node bound, or `None` if it no longer exists."""
    return session.get(AgentProfile, agent_id)


def find_profile(session: Session, role: str, key: str) -> AgentProfile | None:
    return session.scalar(
        select(AgentProfile).where(AgentProfile.role == role, AgentProfile.key == key)
    )


def default_profile(session: Session, role: str) -> AgentProfile | None:
    """The agent a node falls back to when it binds nothing.

    Prefers the explicit `is_default` flag and falls back to the conventional
    `default` key, so a role whose flag was lost still resolves.
    """
    row = session.scalar(
        select(AgentProfile).where(AgentProfile.role == role, AgentProfile.is_default.is_(True))
    )
    return row or find_profile(session, role, DEFAULT_PROFILE_KEY)


def create_profile(
    session: Session,
    *,
    role: str,
    key: str,
    display_name: str,
    description: str = "",
    operations: list[str] | None = None,
    is_default: bool = False,
    default_endpoint_id: str | None = None,
    backup_endpoint_id: str | None = None,
    max_tokens: int | None = None,
    temperature_milli: int | None = None,
    reasoning_model: bool | None = None,
    media_candidates: list[dict[str, Any]] | None = None,
) -> AgentProfile:
    """Creates one agent under a preset role.

    The role's node row is created here on first use, so an operator building
    the first `video_creative` agent does not need a separate "create the
    role" step. A creative role's declared operations come from its preset
    rather than the caller: they are what the media-candidate picker filters
    by, so letting them drift would allow an image endpoint into a video
    agent.
    """
    ensure_node_for_role(session, role)
    if find_profile(session, role, key) is not None:
        raise ValidationFailed(f"角色 {role} 下已存在智能体 {key}。")
    if presets.is_creative(role):
        operations = presets.operations_for(role)
    row = AgentProfile(
        role=role,
        key=key,
        display_name=display_name,
        description=description,
        operations_json=_validated_operations(operations),
        is_default=False,
        enabled=True,
        created_at=utcnow(),
    )
    _apply_bindings(
        session,
        row,
        default_endpoint_id=default_endpoint_id,
        backup_endpoint_id=backup_endpoint_id,
        max_tokens=max_tokens,
        temperature_milli=temperature_milli,
        reasoning_model=reasoning_model,
        media_candidates=media_candidates,
        require_media_candidates=True,
    )
    session.add(row)
    session.flush()
    if is_default or default_profile(session, role) is None:
        _promote_default(session, row)
    return row


def update_profile(
    session: Session,
    profile_id: str,
    *,
    display_name: str | None = None,
    description: str | None = None,
    operations: list[str] | None = None,
    is_default: bool | None = None,
    enabled: bool | None = None,
    default_endpoint_id: str | None = None,
    backup_endpoint_id: str | None = None,
    max_tokens: int | None = None,
    temperature_milli: int | None = None,
    reasoning_model: bool | None = None,
    media_candidates: list[dict[str, Any]] | None = None,
) -> AgentProfile:
    """Edits an agent's metadata.

    `role` is immutable because a graph binds an agent for a specific stage
    and changing the role underneath it would run the wrong kind of agent
    there. `key` is immutable so audit history stays legible."""
    row = get_profile(session, profile_id)
    if display_name is not None:
        row.display_name = display_name
    if description is not None:
        row.description = description
    if operations is not None and not presets.is_creative(row.role):
        # A creative agent's operations are its preset's, not an operator's
        # choice — see `create_profile`.
        row.operations_json = _validated_operations(operations)
    _apply_bindings(
        session,
        row,
        default_endpoint_id=default_endpoint_id,
        backup_endpoint_id=backup_endpoint_id,
        max_tokens=max_tokens,
        temperature_milli=temperature_milli,
        reasoning_model=reasoning_model,
        media_candidates=media_candidates,
        require_media_candidates=False,
    )
    if enabled is not None:
        if not enabled and row.is_default:
            raise ValidationFailed("默认智能体不能停用，请先把另一个智能体设为默认。")
        row.enabled = enabled
    if is_default is True:
        if not row.enabled:
            raise ValidationFailed("已停用的智能体不能设为默认。")
        _promote_default(session, row)
    elif is_default is False and row.is_default:
        raise ValidationFailed("请把另一个智能体设为默认，而不是取消当前默认智能体。")
    session.flush()
    return row


def _apply_bindings(
    session: Session,
    row: AgentProfile,
    *,
    default_endpoint_id: str | None,
    backup_endpoint_id: str | None,
    max_tokens: int | None,
    temperature_milli: int | None,
    reasoning_model: bool | None,
    media_candidates: list[dict[str, Any]] | None,
    require_media_candidates: bool,
) -> None:
    """Validates and writes an agent's model / media bindings.

    `None` means "leave as is" on every argument, following the rest of
    `update_profile`. An **empty string** is how a caller clears a model pin
    and an **empty list** is how it clears media candidates — without that
    distinction there would be no way to go back to the shared pool once an
    endpoint had been pinned.
    """
    creative = presets.is_creative(row.role)

    if creative:
        if media_candidates is not None or require_media_candidates:
            row.media_candidates_json = _validated_media_candidates(
                session, row.role, media_candidates or []
            )
        if default_endpoint_id or backup_endpoint_id:
            raise ValidationFailed("创作类智能体绑定的是媒体候选，不是通用模型端点。")
        return

    if media_candidates:
        raise ValidationFailed("判断类智能体不能绑定媒体候选。")

    endpoints = config_service.get_typed(session, "llm_providers", LlmProviderConfig).endpoints
    if default_endpoint_id is not None:
        row.default_endpoint_id = _validated_general_endpoint(endpoints, default_endpoint_id)
        if row.default_endpoint_id is None:
            # A backup with nothing to back up would silently become the
            # primary — the same rule the table's CHECK constraint enforces.
            row.backup_endpoint_id = None
    if backup_endpoint_id is not None:
        row.backup_endpoint_id = _validated_general_endpoint(endpoints, backup_endpoint_id)
    if row.backup_endpoint_id is not None and row.backup_endpoint_id == row.default_endpoint_id:
        raise ValidationFailed("备用模型不能与默认模型相同。")
    if row.backup_endpoint_id is not None and row.default_endpoint_id is None:
        raise ValidationFailed("先选择默认模型，才能配置备用模型。")

    if max_tokens is not None:
        if not 0 <= max_tokens <= 32_768:
            raise ValidationFailed("max_tokens 需要在 0 到 32768 之间。")
        row.max_tokens = max_tokens or None
    if temperature_milli is not None:
        if not 0 <= temperature_milli <= 2_000:
            raise ValidationFailed("temperature 需要在 0 到 2 之间。")
        row.temperature_milli = temperature_milli
    if reasoning_model is not None:
        row.reasoning_model = reasoning_model


def _validated_general_endpoint(
    endpoints: dict[str, LlmProviderEndpoint], endpoint_id: str
) -> str | None:
    if not endpoint_id:
        return None
    endpoint = endpoints.get(endpoint_id)
    if endpoint is None or not endpoint.enabled or endpoint.kind != "general":
        raise ValidationFailed(f"{endpoint_id} 不是一个已启用的通用模型端点。")
    return endpoint_id


def _validated_media_candidates(
    session: Session, role: str, candidates: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Checks every candidate against the live media pool and the role's preset.

    A creative agent with no candidate is not a half-configured agent, it is
    one the router can never satisfy — so an empty list is rejected rather
    than quietly falling back to the whole catalogue.
    """
    if not candidates:
        raise ValidationFailed("创作类智能体至少需要配置一个媒体候选。")

    endpoints = config_service.get_typed(session, "llm_providers", LlmProviderConfig).endpoints
    allowed_operations = set(presets.operations_for(role))
    seen: set[tuple[str, str]] = set()
    validated: list[dict[str, Any]] = []
    for candidate in candidates:
        endpoint_id = str(candidate.get("endpoint_id") or "")
        capability = str(candidate.get("capability") or "")
        weight = int(candidate.get("weight") or DEFAULT_CANDIDATE_WEIGHT)

        endpoint = endpoints.get(endpoint_id)
        if endpoint is None or not endpoint.enabled or endpoint.kind != "media":
            raise ValidationFailed(f"{endpoint_id} 不是一个已启用的媒体端点。")
        if capability not in endpoint.capabilities:
            raise ValidationFailed(f"{endpoint_id} 不提供 {capability} 能力。")
        if allowed_operations and capability not in allowed_operations:
            raise ValidationFailed(f"{role} 角色不能使用 {capability} 能力。")
        if not MIN_CANDIDATE_WEIGHT <= weight <= MAX_CANDIDATE_WEIGHT:
            raise ValidationFailed(
                f"成本权重需要在 {MIN_CANDIDATE_WEIGHT} 到 {MAX_CANDIDATE_WEIGHT} 之间。"
            )
        if (endpoint_id, capability) in seen:
            raise ValidationFailed(f"媒体候选 {endpoint_id}:{capability} 重复。")
        seen.add((endpoint_id, capability))
        validated.append({"endpoint_id": endpoint_id, "capability": capability, "weight": weight})
    return validated


def _promote_default(session: Session, row: AgentProfile) -> None:
    session.execute(
        update(AgentProfile)
        .where(AgentProfile.role == row.role, AgentProfile.id != row.id)
        .values(is_default=False)
    )
    row.is_default = True
    session.flush()


def _validated_operations(operations: list[str] | None) -> list[str]:
    values = list(dict.fromkeys(operations or []))
    unknown = [value for value in values if value not in _VALID_OPERATIONS]
    if unknown:
        raise ValidationFailed(f"未知的 operation: {sorted(unknown)}")
    return values


# --------------------------------------------------------------------------
# Prompt resolution
# --------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class ResolvedPrompt:
    text: str
    profile: AgentProfile | None


def get_active_prompt(
    session: Session,
    node_role: str,
    default: str,
    *,
    agent_id: str | None = None,
    slot: str = DEFAULT_SLOT,
) -> tuple[str, str | None]:
    """The live prompt for one `(agent, slot)`, plus the agent id."""
    resolved = resolve_prompt(session, node_role, default, agent_id=agent_id, slot=slot)
    return resolved.text, resolved.profile.id if resolved.profile is not None else None


def resolve_prompt(
    session: Session,
    node_role: str,
    default: str,
    *,
    agent_id: str | None = None,
    slot: str = DEFAULT_SLOT,
) -> ResolvedPrompt:
    """The live prompt for one `(agent, slot)`, plus the agent itself.

    The agent comes back rather than just its id because `run_agent` needs
    two things from it: which agent to record on `AgentRun` (without it
    there is no way to verify from the ops console that a binding took
    effect) and which model endpoint the agent pins, if any.

    `node_role` is the role the calling node type declares, and a bound agent
    is only accepted if it has that role: a graph must not be able to run a
    copywriter where the pipeline expects a safety verdict, whatever an
    operator (or a stale id) asks for.

    The `default` argument is always the calling agent module's own
    `SYSTEM_PROMPT` constant, so a fresh deploy with an empty `agent_skills`
    table behaves exactly as it did before this module existed.
    """
    profile: AgentProfile | None = None
    if agent_id:
        candidate = find_agent(session, agent_id)
        if candidate is None or not candidate.enabled or candidate.role != node_role:
            # Publish-time validation rejects all three, so reaching this
            # means the agent was disabled or deleted after a graph went
            # live. Falling back is the safe move; the log line is how an
            # operator finds out.
            logger.warning(
                "workflow bound agent %s for role %s, which is missing, disabled or "
                "of another role; falling back to the role default",
                agent_id,
                node_role,
            )
        else:
            profile = candidate

    if profile is None:
        profile = default_profile(session, node_role)
    if profile is None:
        return ResolvedPrompt(text=default, profile=None)

    skill = session.scalar(
        select(AgentSkill).where(
            AgentSkill.profile_id == profile.id,
            AgentSkill.slot == slot,
            AgentSkill.is_active.is_(True),
        )
    )
    if skill is not None:
        return ResolvedPrompt(text=skill.prompt_template, profile=profile)

    # An agent with nothing published for this slot inherits the role
    # default's prompt rather than the hardcoded one — an operator who forked
    # `safety` only to tweak the video wording should not lose an unrelated
    # slot's published text.
    if not profile.is_default:
        fallback_profile = default_profile(session, node_role)
        if fallback_profile is not None and fallback_profile.id != profile.id:
            inherited = session.scalar(
                select(AgentSkill).where(
                    AgentSkill.profile_id == fallback_profile.id,
                    AgentSkill.slot == slot,
                    AgentSkill.is_active.is_(True),
                )
            )
            if inherited is not None:
                return ResolvedPrompt(text=inherited.prompt_template, profile=profile)

    return ResolvedPrompt(text=default, profile=profile)


# --------------------------------------------------------------------------
# Versions
# --------------------------------------------------------------------------


def list_versions(
    session: Session, *, profile_id: str, slot: str = DEFAULT_SLOT, limit: int = 50
) -> list[AgentSkill]:
    return list(
        session.scalars(
            select(AgentSkill)
            .where(AgentSkill.profile_id == profile_id, AgentSkill.slot == slot)
            .order_by(AgentSkill.version.desc())
            .limit(limit)
        )
    )


def list_nodes(session: Session) -> list[AgentNode]:
    return list(session.scalars(select(AgentNode).order_by(AgentNode.sort_order, AgentNode.role)))


def publish(
    session: Session,
    *,
    profile_id: str,
    slot: str,
    prompt_template: str,
    tool_grants: list[str],
    actor_user_id: str | None,
    reason: str | None,
) -> AgentSkill:
    """Appends a new version for one `(profile, slot)` and activates it."""
    profile = get_profile(session, profile_id)
    if not is_known_slot(profile.role, slot):
        raise ValidationFailed(f"角色 {profile.role} 没有名为 {slot} 的提示词槽位。")

    latest = session.scalar(
        select(AgentSkill.version)
        .where(AgentSkill.profile_id == profile_id, AgentSkill.slot == slot)
        .order_by(AgentSkill.version.desc())
        .limit(1)
    )
    next_version = (latest or 0) + 1

    session.execute(
        update(AgentSkill)
        .where(
            AgentSkill.profile_id == profile_id,
            AgentSkill.slot == slot,
            AgentSkill.is_active.is_(True),
        )
        .values(is_active=False)
    )
    row = AgentSkill(
        node_role=profile.role,
        profile_id=profile_id,
        slot=slot,
        version=next_version,
        prompt_template=prompt_template,
        tool_grants_json=list(tool_grants),
        is_active=True,
        created_by_user_id=actor_user_id,
        reason=reason,
        created_at=utcnow(),
    )
    session.add(row)
    session.flush()
    return row


def activate_version(
    session: Session, skill_id: str, *, actor_user_id: str | None, reason: str | None
) -> AgentSkill:
    """Rolls back by re-publishing an earlier version's content as a new one.

    Moving forward to a copy — rather than flipping `is_active` back onto the
    old row — keeps both the mistake and the correction in history, the same
    trade-off `platform_config.service.rollback` makes.
    """
    target = session.get(AgentSkill, skill_id)
    if target is None:
        raise NotFound(f"技能版本 {skill_id} 不存在。")
    return publish(
        session,
        profile_id=target.profile_id,
        slot=target.slot,
        prompt_template=target.prompt_template,
        tool_grants=list(target.tool_grants_json),
        actor_user_id=actor_user_id,
        reason=reason or f"回滚到版本 {target.version}",
    )


# --------------------------------------------------------------------------
# Seeding
# --------------------------------------------------------------------------


def ensure_default_nodes(session: Session) -> None:
    """Idempotently seeds the platform's built-in nodes.

    Safe to call on every startup/seed run: existing rows (matched by `role`)
    are left untouched so an operator's edits to `display_name`/`enabled`
    survive a redeploy.
    """
    existing_roles = set(session.scalars(select(AgentNode.role)))
    for node in DEFAULT_NODES:
        if node["role"] in existing_roles:
            continue
        session.add(AgentNode(category=presets.category_for(str(node["role"])), **node))
    session.flush()


def ensure_default_profiles(session: Session) -> None:
    """Gives every node role a default agent to fall back to.

    Idempotent and additive: a role that already has any agent flagged
    default is left alone, so an operator who promoted their own agent does
    not get overridden on the next deploy.
    """
    for node in list_nodes(session):
        if default_profile(session, node.role) is not None:
            continue
        create_profile(
            session,
            role=node.role,
            key=DEFAULT_PROFILE_KEY,
            display_name=f"{node.display_name} · 默认",
            description="所有未显式绑定智能体的工作流节点都会回落到这里。",
            operations=[],
            is_default=True,
        )
    session.flush()
