"""User-authored creation skills: create, edit, share, discover, apply."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from app.api import idempotency
from app.api.deps import CurrentUser, DbSession, IdempotencyKey, OptionalUser, rate_limited
from app.api.schemas.common import Page
from app.api.schemas.skill_library import (
    CreationSkillCreateRequest,
    CreationSkillDetail,
    CreationSkillSummary,
    CreationSkillUpdateRequest,
)
from app.api.schemas.works import AuthorSummary
from app.domain.skill_library import service as skill_library
from app.models import CreationSkill, Profile
from app.models.enums import CreationSkillCategory, CreationSkillStatus, CreationSkillVisibility
from app.presenters import media_urls

router = APIRouter(tags=["skills"])

CREATE_ENDPOINT = "POST /v1/skills"


@router.get("/skills/public", response_model=Page[CreationSkillSummary])
def list_public_skills(
    session: DbSession,
    _viewer: OptionalUser,
    __: Annotated[None, Depends(rate_limited("public_read"))],
    category: CreationSkillCategory | None = None,
    cursor: str | None = None,
    limit: int = Query(default=24, ge=1, le=60),
) -> Page[CreationSkillSummary]:
    page = skill_library.list_public(session, category=category, cursor=cursor, limit=limit)
    return Page(
        items=[_summary(session, skill) for skill in page.items],
        next_cursor=page.next_cursor,
        has_more=page.has_more,
    )


@router.get("/skills", response_model=Page[CreationSkillSummary])
def list_my_skills(
    session: DbSession,
    user: CurrentUser,
    _: Annotated[None, Depends(rate_limited("public_read"))],
    limit: int = Query(default=60, ge=1, le=100),
) -> Page[CreationSkillSummary]:
    page = skill_library.list_mine(session, owner_user_id=user.id, limit=limit)
    return Page(
        items=[_summary(session, skill) for skill in page.items],
        next_cursor=page.next_cursor,
        has_more=page.has_more,
    )


@router.get("/skills/{skill_id}", response_model=CreationSkillDetail)
def get_skill(skill_id: str, session: DbSession, viewer: OptionalUser) -> CreationSkillDetail:
    skill = skill_library.get_usable(
        session, skill_id=skill_id, viewer_id=viewer.id if viewer else None
    )
    return _detail(session, skill)


@router.post("/skills", response_model=CreationSkillDetail, status_code=201)
def create_skill(
    payload: CreationSkillCreateRequest,
    user: CurrentUser,
    session: DbSession,
    idempotency_key: IdempotencyKey,
    _: Annotated[None, Depends(rate_limited("authenticated_write"))],
) -> CreationSkillDetail:
    request_hash = idempotency.hash_request(payload.model_dump(mode="json"))
    if idempotency_key:
        replay = idempotency.find_replay(
            session,
            user_id=user.id,
            endpoint=CREATE_ENDPOINT,
            key=idempotency_key,
            request_hash=request_hash,
        )
        if replay is not None:
            return CreationSkillDetail.model_validate(replay.response_snapshot)

    skill = skill_library.create(
        session,
        owner_user_id=user.id,
        title=payload.title,
        description=payload.description,
        category=payload.category,
        params_json=payload.params,
        cover_asset_id=payload.cover_asset_id,
    )
    response = _detail(session, skill)

    if idempotency_key:
        idempotency.remember(
            session,
            user_id=user.id,
            endpoint=CREATE_ENDPOINT,
            key=idempotency_key,
            request_hash=request_hash,
            status_code=201,
            response=response.model_dump(mode="json"),
        )
    session.commit()
    return response


@router.patch("/skills/{skill_id}", response_model=CreationSkillDetail)
def update_skill(
    skill_id: str,
    payload: CreationSkillUpdateRequest,
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("authenticated_write"))],
) -> CreationSkillDetail:
    skill = _require_owned(session, skill_id, user.id)
    skill = skill_library.update(
        session,
        skill=skill,
        actor_user_id=user.id,
        title=payload.title,
        description=payload.description,
        category=payload.category,
        params_json=payload.params,
        cover_asset_id=payload.cover_asset_id,
    )
    session.commit()
    return _detail(session, skill)


@router.post("/skills/{skill_id}/publish", response_model=CreationSkillDetail)
def publish_skill(
    skill_id: str,
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("authenticated_write"))],
) -> CreationSkillDetail:
    skill = _require_owned(session, skill_id, user.id)
    skill = skill_library.publish(session, skill=skill, actor_user_id=user.id)
    session.commit()
    return _detail(session, skill)


@router.post("/skills/{skill_id}/withdraw", response_model=CreationSkillDetail)
def withdraw_skill(
    skill_id: str,
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("authenticated_write"))],
) -> CreationSkillDetail:
    skill = _require_owned(session, skill_id, user.id)
    skill = skill_library.withdraw(session, skill=skill, actor_user_id=user.id)
    session.commit()
    return _detail(session, skill)


@router.post("/skills/{skill_id}/apply", response_model=CreationSkillDetail)
def apply_skill(
    skill_id: str,
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("authenticated_write"))],
) -> CreationSkillDetail:
    skill = skill_library.get_usable(session, skill_id=skill_id, viewer_id=user.id)
    skill = skill_library.record_usage(session, skill=skill)
    session.commit()
    return _detail(session, skill)


def _require_owned(session: DbSession, skill_id: str, owner_user_id: str) -> CreationSkill:
    return skill_library.get_owned(session, skill_id=skill_id, owner_user_id=owner_user_id)


def _summary(session: DbSession, skill: CreationSkill) -> CreationSkillSummary:
    return CreationSkillSummary(
        id=skill.id,
        title=skill.title,
        description=skill.description,
        category=CreationSkillCategory(skill.category),
        cover_url=media_urls.asset_url(session, skill.cover_asset_id),
        author=_author(session, skill.owner_user_id),
        visibility=CreationSkillVisibility(skill.visibility),
        status=CreationSkillStatus(skill.status),
        usage_count=skill.usage_count,
        created_at=skill.created_at,
    )


def _detail(session: DbSession, skill: CreationSkill) -> CreationSkillDetail:
    summary = _summary(session, skill)
    return CreationSkillDetail(
        **summary.model_dump(),
        cover_asset_id=skill.cover_asset_id,
        params=skill.params_json,
        reject_reason=skill.reject_reason,
    )


def _author(session: DbSession, user_id: str) -> AuthorSummary:
    profile = session.scalar(select(Profile).where(Profile.user_id == user_id))
    if profile is None:
        return AuthorSummary(user_id=user_id, display_name="未知作者", handle=user_id)
    return AuthorSummary(
        user_id=user_id,
        display_name=profile.display_name,
        handle=profile.handle,
        avatar_url=media_urls.asset_url(session, profile.avatar_asset_id),
    )
