"""User-authored creation skills: create, edit, share, discover, apply."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from app.api import idempotency
from app.api.deps import CurrentUser, DbSession, IdempotencyKey, OptionalUser, rate_limited
from app.api.schemas.common import Page
from app.api.schemas.skill_library import (
    CreationSkillCreateRequest,
    CreationSkillDetail,
    CreationSkillPricingRequest,
    CreationSkillSummary,
    CreationSkillUpdateRequest,
)
from app.api.schemas.works import AccessGrantView, AccessUnlockResponse, AuthorSummary
from app.domain.access import service as access_service
from app.domain.errors import ValidationFailed
from app.domain.skill_library import service as skill_library
from app.models import CreationSkill, Profile
from app.models.enums import (
    AccessSubjectType,
    CreationSkillCategory,
    CreationSkillStatus,
    CreationSkillVisibility,
    Operation,
)
from app.presenters import media_urls

router = APIRouter(tags=["skills"])

CREATE_ENDPOINT = "POST /v1/skills"


@router.get("/skills/public", response_model=Page[CreationSkillSummary])
def list_public_skills(
    session: DbSession,
    viewer: OptionalUser,
    _: Annotated[None, Depends(rate_limited("public_read"))],
    category: CreationSkillCategory | None = None,
    content_type: Literal["template", "image_asset"] | None = None,
    access: Literal["free", "paid", "all"] = "all",
    cursor: str | None = None,
    limit: int = Query(default=24, ge=1, le=60),
) -> Page[CreationSkillSummary]:
    page = skill_library.list_public(
        session,
        category=category,
        content_type=content_type,
        access=None if access == "all" else access,
        cursor=cursor,
        limit=limit,
    )
    return Page(
        items=[_summary(session, skill, viewer.id if viewer else None) for skill in page.items],
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
        items=[_summary(session, skill, user.id) for skill in page.items],
        next_cursor=page.next_cursor,
        has_more=page.has_more,
    )


@router.get("/skills/{skill_id}", response_model=CreationSkillDetail)
def get_skill(skill_id: str, session: DbSession, viewer: OptionalUser) -> CreationSkillDetail:
    skill = skill_library.get_usable(
        session, skill_id=skill_id, viewer_id=viewer.id if viewer else None
    )
    return _detail(session, skill, viewer.id if viewer else None)


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
        applicable_operations=payload.applicable_operations,
        access_credits=payload.access_credits,
    )
    response = _detail(session, skill, user.id)

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
        applicable_operations=payload.applicable_operations,
    )
    session.commit()
    return _detail(session, skill, user.id)


@router.patch("/skills/{skill_id}/pricing", response_model=CreationSkillDetail)
def update_skill_pricing(
    skill_id: str,
    payload: CreationSkillPricingRequest,
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("authenticated_write"))],
) -> CreationSkillDetail:
    skill = _require_owned(session, skill_id, user.id)
    skill = skill_library.update_pricing(
        session, skill=skill, actor_user_id=user.id, access_credits=payload.access_credits
    )
    session.commit()
    return _detail(session, skill, user.id)


@router.post("/skills/{skill_id}/publish", response_model=CreationSkillDetail)
def publish_skill(
    skill_id: str,
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("authenticated_write"))],
) -> CreationSkillDetail:
    skill = _require_owned(session, skill_id, user.id)
    # A character skill's publish needs a fresh portrait/likeness consent
    # flag this generic route has no field for — `POST /v1/characters/{id}
    # /publish` is the only legal way to share one (see
    # `characters.service.publish_character`). Scene/cover image-asset
    # skills carry no such gate and publish through this route like any
    # template.
    if skill.category == CreationSkillCategory.CHARACTER:
        raise ValidationFailed(
            "角色技能请通过角色发布接口分享（需要肖像授权确认）。",
            fields={"category": "character skills publish via /v1/characters/{id}/publish"},
        )
    skill = skill_library.publish(session, skill=skill, actor_user_id=user.id)
    session.commit()
    return _detail(session, skill, user.id)


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
    return _detail(session, skill, user.id)


@router.delete("/skills/{skill_id}", status_code=204)
def delete_skill(
    skill_id: str,
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("authenticated_write"))],
) -> None:
    skill = _require_owned(session, skill_id, user.id)
    skill_library.delete(session, skill=skill, actor_user_id=user.id)
    session.commit()


UNLOCK_SKILL_ENDPOINT = "POST /v1/skills/{skill_id}/unlock"


@router.post("/skills/{skill_id}/unlock", response_model=AccessUnlockResponse)
def unlock_skill(
    skill_id: str,
    user: CurrentUser,
    session: DbSession,
    idempotency_key: IdempotencyKey,
    _: Annotated[None, Depends(rate_limited("authenticated_write"))],
) -> AccessUnlockResponse:
    request_hash = idempotency.hash_request({"skill_id": skill_id})
    if idempotency_key:
        replay = idempotency.find_replay(
            session,
            user_id=user.id,
            endpoint=UNLOCK_SKILL_ENDPOINT,
            key=idempotency_key,
            request_hash=request_hash,
        )
        if replay is not None:
            return AccessUnlockResponse.model_validate(replay.response_snapshot)

    existing = access_service.get_grant(
        session,
        buyer_user_id=user.id,
        subject_type=AccessSubjectType.SKILL,
        subject_id=skill_id,
    )
    grant = access_service.unlock_skill(session, buyer_user_id=user.id, skill_id=skill_id)
    skill = session.get(CreationSkill, skill_id)
    response = AccessUnlockResponse(
        subject_type=AccessSubjectType.SKILL.value,
        subject_id=skill_id,
        access_credits=skill.access_credits if skill is not None else 0,
        viewer_unlocked=True,
        already_held=existing is not None or grant is None,
        grant=(
            AccessGrantView(
                id=grant.id,
                subject_type=grant.subject_type,
                subject_id=grant.subject_id,
                price_credits=grant.price_credits,
                platform_fee_credits=grant.platform_fee_credits,
                seller_net_credits=grant.seller_net_credits,
                created_at=grant.created_at,
            )
            if grant is not None
            else None
        ),
    )
    if idempotency_key:
        idempotency.remember(
            session,
            user_id=user.id,
            endpoint=UNLOCK_SKILL_ENDPOINT,
            key=idempotency_key,
            request_hash=request_hash,
            status_code=200,
            response=response.model_dump(mode="json"),
        )
    session.commit()
    return response


@router.post("/skills/{skill_id}/apply", response_model=CreationSkillDetail)
def apply_skill(
    skill_id: str,
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("authenticated_write"))],
) -> CreationSkillDetail:
    skill = skill_library.get_usable(session, skill_id=skill_id, viewer_id=user.id)
    skill_library.assert_unlocked_for_use(session, skill, user.id)
    skill = skill_library.record_usage(session, skill=skill)
    session.commit()
    return _detail(session, skill, user.id)


def _require_owned(session: DbSession, skill_id: str, owner_user_id: str) -> CreationSkill:
    return skill_library.get_owned(session, skill_id=skill_id, owner_user_id=owner_user_id)


def _summary(
    session: DbSession, skill: CreationSkill, viewer_id: str | None
) -> CreationSkillSummary:
    return CreationSkillSummary(
        id=skill.id,
        title=skill.title,
        description=skill.description,
        category=CreationSkillCategory(skill.category),
        cover_url=media_urls.asset_url(session, skill.cover_asset_id),
        cover_media_type=media_urls.media_type_of(session, skill.cover_asset_id),
        applicable_operations=[Operation(value) for value in skill.applicable_operations_json],
        author=_author(session, skill.owner_user_id),
        visibility=CreationSkillVisibility(skill.visibility),
        status=CreationSkillStatus(skill.status),
        usage_count=skill.usage_count,
        access_credits=skill.access_credits,
        viewer_unlocked=skill_library.viewer_has_access(session, skill, viewer_id),
        created_at=skill.created_at,
    )


def _detail(session: DbSession, skill: CreationSkill, viewer_id: str | None) -> CreationSkillDetail:
    summary = _summary(session, skill, viewer_id)
    unlocked = summary.viewer_unlocked
    return CreationSkillDetail(
        **summary.model_dump(),
        cover_asset_id=skill.cover_asset_id,
        params=skill.params_json if unlocked else {},
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
