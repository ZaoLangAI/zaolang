"""User-authored creation skills: create, edit, share, review, discover.

A skill starts life as a private `DRAFT` — usable in the owner's own creation
flow immediately, no review needed. `publish()` is the owner opting in to
sharing: it flips `visibility` to `PUBLIC` and files the skill into the same
`moderation_queue_items` table `work`/`asset` already use (subject_type
`"skill"`), rather than a bespoke review path. A human decision on that queue
item is what calls `approve()`/`reject()` here — see
`app/api/v1/admin/content.py::decide()`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.models import Asset, CreationSkill, ModerationQueueItem
from app.models.base import utcnow
from app.models.enums import (
    CreationSkillCategory,
    CreationSkillStatus,
    CreationSkillVisibility,
    ModerationStage,
    ModerationStatus,
)

MAX_DESCRIPTION_LENGTH = 300
QUEUE_STAGE = ModerationStage.SKILL_REVIEW
QUEUE_SUBJECT_TYPE = "skill"


@dataclass(slots=True)
class ListPage:
    items: list[CreationSkill]
    next_cursor: str | None
    has_more: bool


def create(
    session: Session,
    *,
    owner_user_id: str,
    title: str,
    description: str,
    category: CreationSkillCategory,
    params_json: dict[str, Any],
    cover_asset_id: str | None,
) -> CreationSkill:
    _assert_cover_owned(session, owner_user_id=owner_user_id, cover_asset_id=cover_asset_id)
    skill = CreationSkill(
        owner_user_id=owner_user_id,
        title=title,
        description=description,
        category=category,
        params_json=params_json,
        cover_asset_id=cover_asset_id,
        visibility=CreationSkillVisibility.PRIVATE,
        status=CreationSkillStatus.DRAFT,
    )
    session.add(skill)
    session.flush()
    return skill


def update(
    session: Session,
    *,
    skill: CreationSkill,
    actor_user_id: str,
    title: str,
    description: str,
    category: CreationSkillCategory,
    params_json: dict[str, Any],
    cover_asset_id: str | None,
) -> CreationSkill:
    if skill.owner_user_id != actor_user_id:
        raise Forbidden("只能编辑自己创建的技能。")

    _assert_cover_owned(session, owner_user_id=actor_user_id, cover_asset_id=cover_asset_id)

    skill.title = title
    skill.description = description
    skill.category = category
    skill.params_json = params_json
    skill.cover_asset_id = cover_asset_id

    # 已公开或正在审核的技能一旦改动内容，视为撤回分享——必须重新走 publish()。
    if skill.status != CreationSkillStatus.DRAFT:
        _unpublish(skill)

    session.flush()
    return skill


def withdraw(session: Session, *, skill: CreationSkill, actor_user_id: str) -> CreationSkill:
    """Owner takes a shared skill back to private, at any point in its lifecycle."""
    if skill.owner_user_id != actor_user_id:
        raise Forbidden("只能撤回自己创建的技能。")
    _unpublish(skill)
    _resolve_open_queue_item(session, skill)
    session.flush()
    return skill


def publish(session: Session, *, skill: CreationSkill, actor_user_id: str) -> CreationSkill:
    """Owner asks to share this skill; files it for human review."""
    if skill.owner_user_id != actor_user_id:
        raise Forbidden("只能分享自己创建的技能。")
    if skill.status == CreationSkillStatus.PENDING_REVIEW:
        return skill
    if skill.status == CreationSkillStatus.PUBLISHED:
        return skill

    skill.visibility = CreationSkillVisibility.PUBLIC
    skill.status = CreationSkillStatus.PENDING_REVIEW
    skill.reject_reason = None
    _reopen_queue_item(session, skill)
    session.flush()
    return skill


def get_owned(session: Session, *, skill_id: str, owner_user_id: str) -> CreationSkill:
    skill = session.get(CreationSkill, skill_id)
    if skill is None or skill.owner_user_id != owner_user_id:
        raise NotFound("技能不存在。")
    return skill


def get_usable(session: Session, *, skill_id: str, viewer_id: str | None) -> CreationSkill:
    """A skill can be applied by its owner (any status) or anyone once published."""
    skill = session.get(CreationSkill, skill_id)
    if skill is None:
        raise NotFound("技能不存在。")
    if skill.status == CreationSkillStatus.PUBLISHED:
        return skill
    if viewer_id is not None and skill.owner_user_id == viewer_id:
        return skill
    raise NotFound("技能不存在。")


def record_usage(session: Session, *, skill: CreationSkill) -> CreationSkill:
    skill.usage_count += 1
    session.flush()
    return skill


def list_mine(session: Session, *, owner_user_id: str, limit: int = 60) -> ListPage:
    stmt = (
        select(CreationSkill)
        .where(CreationSkill.owner_user_id == owner_user_id)
        .order_by(CreationSkill.created_at.desc(), CreationSkill.id.desc())
        .limit(limit + 1)
    )
    rows = list(session.scalars(stmt))
    has_more = len(rows) > limit
    return ListPage(items=rows[:limit], next_cursor=None, has_more=has_more)


def list_public(
    session: Session,
    *,
    category: CreationSkillCategory | None = None,
    cursor: str | None = None,
    limit: int = 24,
) -> ListPage:
    anchor: CreationSkill | None = None
    if cursor:
        anchor = session.get(CreationSkill, cursor)
        if anchor is None or anchor.status != CreationSkillStatus.PUBLISHED:
            return ListPage(items=[], next_cursor=None, has_more=False)

    stmt = select(CreationSkill).where(CreationSkill.status == CreationSkillStatus.PUBLISHED)
    if category:
        stmt = stmt.where(CreationSkill.category == category)
    stmt = stmt.order_by(CreationSkill.created_at.desc(), CreationSkill.id.desc())
    if anchor is not None:
        stmt = stmt.where(
            (CreationSkill.created_at < anchor.created_at)
            | ((CreationSkill.created_at == anchor.created_at) & (CreationSkill.id < anchor.id))
        )

    rows = list(session.scalars(stmt.limit(limit + 1)))
    has_more = len(rows) > limit
    items = rows[:limit]
    return ListPage(
        items=items, next_cursor=items[-1].id if has_more and items else None, has_more=has_more
    )


def admin_list(
    session: Session, *, status: CreationSkillStatus | None = None, limit: int = 50
) -> list[CreationSkill]:
    """Global browse for the ops console — `None` means every status, not
    just pending review (that narrower view is the moderation queue's job)."""
    stmt = select(CreationSkill).order_by(CreationSkill.created_at.desc()).limit(limit)
    if status:
        stmt = stmt.where(CreationSkill.status == status)
    return list(session.scalars(stmt))


def approve(session: Session, *, skill: CreationSkill, reviewer_user_id: str) -> CreationSkill:
    if skill.status != CreationSkillStatus.PENDING_REVIEW:
        raise Conflict("只能对待审核技能做出审核决定。")

    skill.status = CreationSkillStatus.PUBLISHED
    skill.reviewed_by_user_id = reviewer_user_id
    skill.reviewed_at = utcnow()
    skill.reject_reason = None
    session.flush()
    return skill


def reject(
    session: Session, *, skill: CreationSkill, reviewer_user_id: str, reason: str
) -> CreationSkill:
    if skill.status != CreationSkillStatus.PENDING_REVIEW:
        raise Conflict("只能对待审核技能做出审核决定。")
    if not reason.strip():
        raise ValidationFailed("拒绝必须填写理由。")

    skill.status = CreationSkillStatus.REJECTED
    skill.visibility = CreationSkillVisibility.PRIVATE
    skill.reviewed_by_user_id = reviewer_user_id
    skill.reviewed_at = utcnow()
    skill.reject_reason = reason
    session.flush()
    return skill


def admin_takedown(
    session: Session, *, skill: CreationSkill, actor_user_id: str, reason: str
) -> CreationSkill:
    """Operator force-unpublishes a skill that already cleared review.

    Unlike `reject()` this does not require `PENDING_REVIEW` — a takedown can
    hit a skill at any point after it went live.
    """
    if not reason.strip():
        raise ValidationFailed("下架必须填写理由。")

    skill.status = CreationSkillStatus.REJECTED
    skill.visibility = CreationSkillVisibility.PRIVATE
    skill.reject_reason = reason
    skill.reviewed_by_user_id = actor_user_id
    skill.reviewed_at = utcnow()
    session.flush()
    return skill


def _unpublish(skill: CreationSkill) -> None:
    skill.status = CreationSkillStatus.DRAFT
    skill.visibility = CreationSkillVisibility.PRIVATE
    skill.reject_reason = None


def _queue_item_for(session: Session, skill: CreationSkill) -> ModerationQueueItem | None:
    """At most one row can ever exist per (subject_type, subject_id, stage) —
    `uq_moderation_queue_subject` has no `status` in its key — so a skill's
    review history lives in one row that gets reopened, not appended to."""
    return session.scalar(
        select(ModerationQueueItem).where(
            ModerationQueueItem.subject_type == QUEUE_SUBJECT_TYPE,
            ModerationQueueItem.subject_id == skill.id,
            ModerationQueueItem.stage == QUEUE_STAGE,
        )
    )


def _reopen_queue_item(session: Session, skill: CreationSkill) -> None:
    item = _queue_item_for(session, skill)
    if item is None:
        session.add(
            ModerationQueueItem(
                subject_type=QUEUE_SUBJECT_TYPE,
                subject_id=skill.id,
                stage=QUEUE_STAGE,
                status=ModerationStatus.NEEDS_REVIEW,
            )
        )
        return
    item.status = ModerationStatus.NEEDS_REVIEW
    item.claimed_by_user_id = None
    item.reason_code = None
    item.resolved_at = None


def _resolve_open_queue_item(session: Session, skill: CreationSkill) -> None:
    """Owner-initiated withdrawal closes a queue item still awaiting review."""
    item = _queue_item_for(session, skill)
    if item is not None and item.status == ModerationStatus.NEEDS_REVIEW:
        item.status = ModerationStatus.REJECTED
        item.resolved_at = utcnow()
        item.reason_code = "withdrawn_by_owner"


def _assert_cover_owned(
    session: Session, *, owner_user_id: str, cover_asset_id: str | None
) -> None:
    if not cover_asset_id:
        return
    asset = session.get(Asset, cover_asset_id)
    if asset is None or asset.owner_user_id != owner_user_id:
        raise ValidationFailed("素材不存在或不属于当前用户。", asset_id=cover_asset_id)
