"""Short-video specs, pre-publish compliance and export intents."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api import idempotency
from app.api.deps import CurrentUser, DbSession, IdempotencyKey, rate_limited
from app.api.schemas.common import Page
from app.api.schemas.shortform import (
    ComplianceCheckItem,
    ComplianceCheckRequest,
    ComplianceCheckResponse,
    PromptEnhanceRequest,
    PromptEnhanceResponse,
    PublicationCreateRequest,
    PublicationIntentResponse,
    ShortformProfileResponse,
    ShortformProfilesResponse,
)
from app.domain.errors import ValidationFailed
from app.domain.shortform import service as shortform
from app.models import PublicationIntent
from app.models.enums import DistributionChannel, PublicationStatus
from app.platform_config import service as config_service
from app.platform_config.schemas import ShortformProfile

router = APIRouter(tags=["shortform"])

PUBLICATIONS_ENDPOINT = "POST /v1/works/{work_id}/publications"


@router.get("/shortform/profiles", response_model=ShortformProfilesResponse)
def list_profiles(
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("public_read"))],
) -> ShortformProfilesResponse:
    """The spec catalogue the studio renders its selector and limits from."""
    catalog = shortform.catalog(session)
    return ShortformProfilesResponse(
        default_profile=catalog.default_profile,
        profiles=[_profile_response(key, p) for key, p in sorted(catalog.profiles.items())],
    )


@router.post("/shortform/compliance-check", response_model=ComplianceCheckResponse)
def compliance_check(
    payload: ComplianceCheckRequest,
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("authenticated_write"))],
) -> ComplianceCheckResponse:
    """Checks one clip and its caption against a spec, rule by rule."""
    _assert_shortform_enabled(session, user.id)

    report = shortform.check_compliance(
        session,
        user_id=user.id,
        draft_id=payload.draft_id,
        asset_id=payload.asset_id,
        profile_key=payload.profile,
        title=payload.title,
        description=payload.description,
        hashtags=payload.hashtags,
    )
    # The safety verdict is persisted, so the check has to be committed.
    session.commit()

    return ComplianceCheckResponse(
        profile=_profile_response(report.profile_key, report.profile),
        checks=[
            ComplianceCheckItem(code=c.code, level=c.level, message=c.message)
            for c in report.checks
        ],
        passed=report.passed,
    )


@router.post("/shortform/prompt/enhance", response_model=PromptEnhanceResponse)
def enhance_prompt(
    payload: PromptEnhanceRequest,
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("authenticated_write"))],
) -> PromptEnhanceResponse:
    """把画面描述交给文案 Agent 润色，保留用户核心意图。"""
    _assert_shortform_enabled(session, user.id)
    enhanced, degraded = shortform.enhance_prompt(session, user_id=user.id, prompt=payload.prompt)
    session.commit()
    return PromptEnhanceResponse(prompt=enhanced, degraded=degraded)


@router.post(
    "/works/{work_id}/publications", response_model=PublicationIntentResponse, status_code=201
)
def create_publication(
    work_id: str,
    payload: PublicationCreateRequest,
    user: CurrentUser,
    session: DbSession,
    idempotency_key: IdempotencyKey,
    _: Annotated[None, Depends(rate_limited("authenticated_write"))],
) -> PublicationIntentResponse:
    """Records an export intent and returns the material to post with.

    Direct publishing is not implemented; the intent exists so the history is
    already there when it is.
    """
    _assert_shortform_enabled(session, user.id)

    request_hash = idempotency.hash_request({"work_id": work_id, **payload.model_dump(mode="json")})
    if idempotency_key:
        replay = idempotency.find_replay(
            session,
            user_id=user.id,
            endpoint=PUBLICATIONS_ENDPOINT,
            key=idempotency_key,
            request_hash=request_hash,
        )
        if replay is not None:
            return PublicationIntentResponse.model_validate(replay.response_snapshot)

    bundle = shortform.create_publication_intent(
        session,
        user_id=user.id,
        work_id=work_id,
        channel=payload.channel,
        title=payload.title,
        description=payload.description,
        hashtags=payload.hashtags,
        cover_asset_id=payload.cover_asset_id,
        scheduled_at=payload.scheduled_at,
    )
    response = _intent_response(bundle.intent, bundle.download_url)

    if idempotency_key:
        idempotency.remember(
            session,
            user_id=user.id,
            endpoint=PUBLICATIONS_ENDPOINT,
            key=idempotency_key,
            request_hash=request_hash,
            status_code=201,
            response=response.model_dump(mode="json"),
        )
    session.commit()
    return response


@router.get("/works/{work_id}/publications", response_model=Page[PublicationIntentResponse])
def list_publications(
    work_id: str,
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("public_read"))],
    limit: int = Query(default=20, ge=1, le=50),
) -> Page[PublicationIntentResponse]:
    intents = shortform.list_publication_intents(
        session, user_id=user.id, work_id=work_id, limit=limit
    )
    download_url = shortform.export_url_for(session, work_id=work_id, user_id=user.id)
    return Page(items=[_intent_response(intent, download_url) for intent in intents])


def _assert_shortform_enabled(session: DbSession, user_id: str) -> None:
    if not config_service.is_enabled(session, "shortform_studio", user_id=user_id):
        raise ValidationFailed("短视频创作暂未开放。")


def _profile_response(key: str, profile: ShortformProfile) -> ShortformProfileResponse:
    return ShortformProfileResponse(key=key, **profile.model_dump())


def _intent_response(
    intent: PublicationIntent, download_url: str | None
) -> PublicationIntentResponse:
    return PublicationIntentResponse(
        id=intent.id,
        work_id=intent.work_id,
        channel=DistributionChannel(intent.channel),
        status=PublicationStatus(intent.status),
        payload=intent.payload_json,
        download_url=download_url,
        external_post_id=intent.external_post_id,
        submitted_at=intent.submitted_at,
        created_at=intent.created_at,
    )
