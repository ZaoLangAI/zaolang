"""Drafts and publication."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.api.schemas.common import Page
from app.api.schemas.works import (
    DraftCreateRequest,
    DraftResponse,
    LicenseInfo,
    PublishRequest,
    PublishResponse,
)
from app.domain.errors import Forbidden, NotFound, ValidationFailed
from app.domain.publishing import service as publishing
from app.models import Draft, LicenseSnapshot
from app.models.enums import Visibility
from app.presenters import media_urls

router = APIRouter(prefix="/drafts", tags=["drafts"])


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


@router.post("/{draft_id}/publish", response_model=PublishResponse, status_code=201)
def publish(
    draft_id: str, payload: PublishRequest, user: CurrentUser, session: DbSession
) -> PublishResponse:
    """Publishes a draft as one transaction.

    Everything from the licence re-check to the ancestor notification either
    lands together or not at all.
    """
    if not payload.ai_disclosure_confirmed:
        raise ValidationFailed(
            "请确认作品由 AI 生成的声明。", fields={"ai_disclosure_confirmed": "必须勾选"}
        )

    outcome = publishing.publish(
        session,
        user_id=user.id,
        draft_id=draft_id,
        title=payload.title,
        description=payload.description,
        visibility=payload.visibility,
        tags=payload.tags,
        cover_asset_id=payload.cover_asset_id,
        rights_confirmed=payload.rights_confirmed,
    )
    session.commit()

    return PublishResponse(
        work_id=outcome.work.id,
        work_version_id=outcome.version.id,
        visibility=Visibility(outcome.work.visibility),
        lineage_edge_id=outcome.lineage_edge.id if outcome.lineage_edge else None,
        royalties_paid=outcome.royalties,
    )


@router.delete("/{draft_id}", status_code=204)
def delete_draft(draft_id: str, user: CurrentUser, session: DbSession) -> None:
    draft = _owned(session, draft_id, user.id)
    if draft.published_work_id is not None:
        raise ValidationFailed("已发布的草稿不能删除。")
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
        published_work_id=draft.published_work_id,
        created_at=draft.created_at,
    )
