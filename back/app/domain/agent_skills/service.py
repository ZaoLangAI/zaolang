"""Versioned agent prompts, append-only like `platform_config.service`.

Publishing never overwrites a row: it appends a new version and flips the
active flag inside one transaction, so any earlier prompt can be replayed by
re-publishing its content as the newest version. There is deliberately no
`update()` — editing a live prompt in place would erase the ability to explain
why a generation behaved the way it did.

Prompts hang off a `(profile, slot)` pair rather than off the role directly:

* a **profile** is a named variant of a role, so `text_to_video` can run a
  stricter safety prompt than `text_to_image` without either workflow having
  to fork the agent code;
* a **slot** separates the several system prompts one role may own (see
  `app.agents.slots`).

Resolution is deliberately forgiving at runtime — bound variant, then the
role's default variant, then the calling module's own constant. A missing
variant must degrade to a working prompt, never to an empty one; publish-time
validation is where a typo gets caught (`workflow_templates.service`).
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.agents.slots import DEFAULT_SLOT, is_known_slot
from app.domain.errors import NotFound, ValidationFailed
from app.models import AgentNode, AgentProfile, AgentSkill
from app.models.base import utcnow
from app.models.enums import Operation

logger = logging.getLogger(__name__)

DEFAULT_PROFILE_KEY = "default"

# Seeded once at startup/seed time; an operator can add more nodes later
# through the same table, so this is only the platform's built-in starting set.
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
        raise NotFound(f"智能体变体 {profile_id} 不存在。")
    return row


def find_profile(session: Session, role: str, key: str) -> AgentProfile | None:
    return session.scalar(
        select(AgentProfile).where(AgentProfile.role == role, AgentProfile.key == key)
    )


def default_profile(session: Session, role: str) -> AgentProfile | None:
    """The variant a node falls back to when it binds nothing.

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
) -> AgentProfile:
    if find_profile(session, role, key) is not None:
        raise ValidationFailed(f"角色 {role} 下已存在变体 {key}。")
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
) -> AgentProfile:
    """Edits a variant's metadata. `role` and `key` are immutable: every
    published graph references the key, so renaming it would silently
    re-point live workflows."""
    row = get_profile(session, profile_id)
    if display_name is not None:
        row.display_name = display_name
    if description is not None:
        row.description = description
    if operations is not None:
        row.operations_json = _validated_operations(operations)
    if enabled is not None:
        if not enabled and row.is_default:
            raise ValidationFailed("默认变体不能停用，请先把另一个变体设为默认。")
        row.enabled = enabled
    if is_default is True:
        if not row.enabled:
            raise ValidationFailed("已停用的变体不能设为默认。")
        _promote_default(session, row)
    elif is_default is False and row.is_default:
        raise ValidationFailed("请把另一个变体设为默认，而不是取消当前默认变体。")
    session.flush()
    return row


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


def get_active_prompt(
    session: Session,
    node_role: str,
    default: str,
    *,
    profile_key: str | None = None,
    slot: str = DEFAULT_SLOT,
) -> tuple[str, str | None]:
    """The live prompt for one `(role, variant, slot)`, plus the variant id.

    Returns the resolved profile id alongside the text so the caller can
    record on `AgentRun` which variant actually ran — without it there is no
    way to verify from the ops console that a binding took effect.

    The `default` argument is always the calling agent module's own
    `SYSTEM_PROMPT` constant, so a fresh deploy with an empty `agent_skills`
    table behaves exactly as it did before this module existed.
    """
    profile: AgentProfile | None = None
    if profile_key:
        candidate = find_profile(session, node_role, profile_key)
        if candidate is None or not candidate.enabled:
            # Publish-time validation rejects this, so reaching it means a
            # variant was disabled after a graph went live. Falling back is
            # the safe move; the log line is how an operator finds out.
            logger.warning(
                "workflow bound agent profile %s/%s which is missing or disabled; "
                "falling back to the role default",
                node_role,
                profile_key,
            )
        else:
            profile = candidate

    if profile is None:
        profile = default_profile(session, node_role)
    if profile is None:
        return default, None

    skill = session.scalar(
        select(AgentSkill).where(
            AgentSkill.profile_id == profile.id,
            AgentSkill.slot == slot,
            AgentSkill.is_active.is_(True),
        )
    )
    if skill is not None:
        return skill.prompt_template, profile.id

    # A variant with nothing published for this slot inherits the role
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
                return inherited.prompt_template, profile.id

    return default, profile.id


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
        session.add(AgentNode(**node))
    session.flush()


def ensure_default_profiles(session: Session) -> None:
    """Gives every node role a default variant to fall back to.

    Idempotent and additive: a role that already has any variant flagged
    default is left alone, so an operator who promoted their own variant does
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
            description="所有未显式绑定变体的工作流节点都会回落到这里。",
            operations=[],
            is_default=True,
        )
    session.flush()
