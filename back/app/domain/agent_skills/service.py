"""Versioned agent prompts, append-only like `platform_config.service`.

Publishing never overwrites a row: it appends a new version and flips the
active flag inside one transaction, so any earlier prompt can be replayed by
re-publishing its content as the newest version. There is deliberately no
`update()` — editing a live prompt in place would erase the ability to explain
why a generation behaved the way it did.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.domain.errors import NotFound
from app.models import AgentNode, AgentSkill
from app.models.base import utcnow

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


def get_active_prompt(session: Session, node_role: str, default: str) -> str:
    """The live prompt for one node, falling back to the caller's own default.

    The default is always the calling agent module's own `SYSTEM_PROMPT`
    constant, so a fresh deploy with an empty `agent_skills` table behaves
    exactly as it did before this module existed.
    """
    skill = session.scalar(
        select(AgentSkill).where(AgentSkill.node_role == node_role, AgentSkill.is_active.is_(True))
    )
    return skill.prompt_template if skill else default


def list_versions(session: Session, node_role: str, limit: int = 50) -> list[AgentSkill]:
    return list(
        session.scalars(
            select(AgentSkill)
            .where(AgentSkill.node_role == node_role)
            .order_by(AgentSkill.version.desc())
            .limit(limit)
        )
    )


def list_nodes(session: Session) -> list[AgentNode]:
    return list(session.scalars(select(AgentNode).order_by(AgentNode.sort_order, AgentNode.role)))


def publish(
    session: Session,
    *,
    node_role: str,
    prompt_template: str,
    tool_grants: list[str],
    actor_user_id: str | None,
    reason: str | None,
) -> AgentSkill:
    """Appends a new version for `node_role` and makes it the active one."""
    latest = session.scalar(
        select(AgentSkill.version)
        .where(AgentSkill.node_role == node_role)
        .order_by(AgentSkill.version.desc())
        .limit(1)
    )
    next_version = (latest or 0) + 1

    session.execute(
        update(AgentSkill)
        .where(AgentSkill.node_role == node_role, AgentSkill.is_active.is_(True))
        .values(is_active=False)
    )
    row = AgentSkill(
        node_role=node_role,
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
        node_role=target.node_role,
        prompt_template=target.prompt_template,
        tool_grants=list(target.tool_grants_json),
        actor_user_id=actor_user_id,
        reason=reason or f"回滚到版本 {target.version}",
    )


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
