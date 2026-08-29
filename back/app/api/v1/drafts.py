"""Drafts and publication."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.api import idempotency
from app.api.deps import CurrentUser, DbSession, IdempotencyKey, rate_limited
from app.api.schemas.common import Page
from app.api.schemas.works import (
    DraftCreateRequest,
    DraftResponse,
    LicenseInfo,
    PublishRequest,
    PublishResponse,
)
from app.domain.errors import Forbidden, NotFound, ProviderTemporaryFailure, ValidationFailed
from app.domain.publishing import service as publishing
from app.models import Asset, Draft, LicenseSnapshot
from app.models.enums import DraftPublishStatus, MediaType
from app.presenters import media_urls

router = APIRouter(prefix="/drafts", tags=["drafts"])

PUBLISH_ENDPOINT = "POST /v1/drafts/{draft_id}/publish"


@router.post("", response_model=DraftResponse, status_code=201)
def create_draft(
    payload: DraftCreateRequest, user: CurrentUser, session: DbSession
) -> DraftResponse:
    """Starts a draft, capturing the source licence at this moment."""
    draft = publishing.create_draft(
        session,
        user_id=user.id,
        source_work_id=payload.source_work_id,
        title=payload.title,
        params=payload.params,
    )
    session.commit()
    return _response(session, draft)


@router.get("", response_model=Page[DraftResponse])
def list_drafts(user: CurrentUser, session: DbSession) -> Page[DraftResponse]:
    drafts = session.scalars(
        select(Draft)
        .where(Draft.user_id == user.id, Draft.published_work_id.is_(None))
        .order_by(Draft.created_at.desc())
        .limit(50)
    )
    return Page(items=[_response(session, d) for d in drafts])


@router.get("/{draft_id}", response_model=DraftResponse)
def get_draft(draft_id: str, user: CurrentUser, session: DbSession) -> DraftResponse:
    return _response(session, _owned(session, draft_id, user.id))


@router.post("/{draft_id}/publish", response_model=PublishResponse, status_code=202)
def publish(
    draft_id: str,
    payload: PublishRequest,
    user: CurrentUser,
    session: DbSession,
    idempotency_key: IdempotencyKey,
    _: Annotated[None, Depends(rate_limited("authenticated_write"))],
) -> PublishResponse:
    """Accepts a publish intent. Safety review and Work creation run in a worker."""
    if not payload.ai_disclosure_confirmed:
        raise ValidationFailed(
            "请确认作品由 AI 生成的声明。", fields={"ai_disclosure_confirmed": "必须勾选"}
        )

    request_hash = idempotency.hash_request(
        {"draft_id": draft_id, **payload.model_dump(mode="json")}
    )
    if idempotency_key:
        replay = idempotency.find_replay(
            session,
            user_id=user.id,
            endpoint=PUBLISH_ENDPOINT,
            key=idempotency_key,
            request_hash=request_hash,
        )
        if replay is not None:
            return PublishResponse.model_validate(replay.response_snapshot)

    draft = publishing.request_publish(
        session,
        user_id=user.id,
        draft_id=draft_id,
        title=payload.title,
        description=payload.description,
        visibility=payload.visibility,
        tags=payload.tags,
        cover_asset_id=payload.cover_asset_id,
        rights_confirmed=payload.rights_confirmed,
        access_credits=payload.access_credits,
    )
    response = PublishResponse(status="pending", draft_id=draft.id)
    session.commit()

    try:
        publishing.enqueue_draft_publish(draft.id)
    except Exception as exc:
        publishing.revert_publish_request(session, draft)
        session.commit()
        raise ProviderTemporaryFailure("发布任务未能入队，请重试。") from exc

    if idempotency_key:
        idempotency.remember(
            session,
            user_id=user.id,
            endpoint=PUBLISH_ENDPOINT,
            key=idempotency_key,
            request_hash=request_hash,
            status_code=202,
            response=response.model_dump(mode="json"),
        )
        session.commit()

    return response


@router.delete("/{draft_id}", status_code=204)
def delete_draft(draft_id: str, user: CurrentUser, session: DbSession) -> None:
    draft = _owned(session, draft_id, user.id)
    if draft.published_work_id is not None:
        raise ValidationFailed("已发布的草稿不能删除。")
    if draft.publish_status == DraftPublishStatus.PENDING:
        raise ValidationFailed("正在审核发布的草稿不能删除。")
    session.delete(draft)
    session.commit()


def _owned(session, draft_id: str, user_id: str) -> Draft:  # type: ignore[no-untyped-def]
    draft = session.get(Draft, draft_id)
    if draft is None:
        raise NotFound("草稿不存在。")
    if draft.user_id != user_id:
        raise Forbidden("不能访问他人的草稿。")
    return draft


def _response(session, draft: Draft) -> DraftResponse:  # type: ignore[no-untyped-def]
    license_info = None
    if draft.license_snapshot_id:
        snapshot = session.get(LicenseSnapshot, draft.license_snapshot_id)
        if snapshot is not None:
            license_info = LicenseInfo(
                license_type=snapshot.license_type,
                attribution_text=snapshot.attribution_text,
                permissions=snapshot.permissions_json,
                captured_at=snapshot.captured_at,
            )

    asset = session.get(Asset, draft.output_asset_id) if draft.output_asset_id else None
    publish_status = None
    if draft.publish_status:
        publish_status = DraftPublishStatus(draft.publish_status)
    return DraftResponse(
        id=draft.id,
        source_work_version_id=draft.source_work_version_id,
        title=draft.title,
        description=draft.description,
        params=draft.params_json,
        license=license_info,
        latest_job_id=draft.latest_job_id,
        output_asset_id=draft.output_asset_id,
        output_url=media_urls.asset_url(session, draft.output_asset_id),
        output_media_type=MediaType(asset.media_type) if asset else None,
        duration_ms=asset.duration_ms if asset else None,
        width=asset.width if asset else None,
        height=asset.height if asset else None,
        published_work_id=draft.published_work_id,
        publish_status=publish_status,
        publish_failure_message=draft.publish_failure_message,
        created_at=draft.created_at,
    )
