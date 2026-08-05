"""Back-office oversight for user-authored creation skills.

Distinct from `admin/content.py`'s moderation queue, which only ever surfaces
a skill while it sits `PENDING_REVIEW`: this is the always-available global
browse plus an operator's own takedown action for a skill that already
cleared review and later turned out to need removal.
"""

from __future__ import annotations

from fastapi import APIRouter, Query, Request

from app.api.deps import DbSession
from app.api.schemas.admin import CreationSkillAdminView, TombstoneRequest
from app.api.schemas.common import Page
from app.api.v1.admin.deps import AdminDangerous, AdminRead, Operator, Viewer, require_confirmation
from app.domain.audit import service as audit
from app.domain.errors import NotFound
from app.domain.notifications import push as notifications
from app.domain.skill_library import service as skill_library
from app.models import CreationSkill
from app.models.enums import CreationSkillStatus, NotificationType
from app.presenters import media_urls

router = APIRouter(tags=["admin:skill-library"])


@router.get("/skills", response_model=Page[CreationSkillAdminView])
def list_skills(
    session: DbSession,
    user: Viewer,
    _: AdminRead,
    status: CreationSkillStatus | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> Page[CreationSkillAdminView]:
    skills = skill_library.admin_list(session, status=status, limit=limit)
    return Page(items=[_view(session, skill) for skill in skills])


@router.post("/skills/{skill_id}/takedown", response_model=CreationSkillAdminView)
def takedown_skill(
    skill_id: str,
    payload: TombstoneRequest,
    request: Request,
    session: DbSession,
    user: Operator,
    __: AdminDangerous,
) -> CreationSkillAdminView:
    require_confirmation(payload.confirm)
    skill = session.get(CreationSkill, skill_id)
    if skill is None:
        raise NotFound("技能不存在。")

    before = {"status": skill.status}
    skill_library.admin_takedown(session, skill=skill, actor_user_id=user.id, reason=payload.reason)
    notifications.notify(
        session,
        user_id=skill.owner_user_id,
        type=NotificationType.MODERATION,
        title_key="notification.skill_takedown",
        payload={"title": skill.title, "reason": payload.reason},
        target_type="skill",
        target_id=skill.id,
    )
    audit.record(
        session,
        actor=user,
        action="skill.takedown",
        target_type="skill",
        target_id=skill.id,
        before=before,
        after={"status": skill.status},
        reason=payload.reason,
        request=request,
    )
    session.commit()
    return _view(session, skill)


def _view(session: DbSession, skill: CreationSkill) -> CreationSkillAdminView:
    return CreationSkillAdminView(
        id=skill.id,
        owner_user_id=skill.owner_user_id,
        title=skill.title,
        description=skill.description,
        category=skill.category,
        cover_url=media_urls.asset_url(session, skill.cover_asset_id),
        visibility=skill.visibility,
        status=skill.status,
        usage_count=skill.usage_count,
        reject_reason=skill.reject_reason,
        created_at=skill.created_at,
    )
