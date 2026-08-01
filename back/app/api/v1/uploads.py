"""Upload handshake and asset access."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import CurrentUser, DbSession, OptionalUser, rate_limited
from app.api.schemas.jobs import (
    AssetResponse,
    ProvenanceResponse,
    UploadCompleteRequest,
    UploadPresignRequest,
    UploadPresignResponse,
)
from app.domain.errors import NotFound
from app.domain.media import service as media_service
from app.models import Asset
from app.models.enums import ADMIN_ROLE_RANK, AssetRole, MediaType
from app.presenters import media_urls

router = APIRouter(tags=["assets"])


@router.post("/uploads/presign", response_model=UploadPresignResponse)
def presign(
    payload: UploadPresignRequest,
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("upload_presign"))],
) -> UploadPresignResponse:
    """Issues a scoped upload URL.

    The signature is bound to one key, MIME type and content length, so it
    cannot be reused to write anything else into the bucket.
    """
    presigned = media_service.presign_upload(
        session,
        user_id=user.id,
        filename=payload.filename,
        mime_type=payload.mime_type,
        size_bytes=payload.size_bytes,
        checksum_sha256=payload.checksum_sha256,
        purpose=payload.purpose,
    )
    session.commit()
    return UploadPresignResponse(
        upload_session_id=presigned.upload_session.id,
        upload_url=presigned.upload_url,
        object_key=presigned.upload_session.object_key,
        expires_at=presigned.upload_session.expires_at,
        required_headers=presigned.required_headers,
    )


@router.post("/uploads/complete", response_model=AssetResponse, status_code=201)
def complete(
    payload: UploadCompleteRequest, user: CurrentUser, session: DbSession
) -> AssetResponse:
    """Verifies the stored object against what was promised, then registers it."""
    asset = media_service.complete_upload(
        session, user_id=user.id, upload_session_id=payload.upload_session_id
    )
    session.commit()
    return _asset_response(session, asset, viewer_id=user.id)


@router.get("/assets/{asset_id}", response_model=AssetResponse)
def get_asset(asset_id: str, session: DbSession, viewer: OptionalUser) -> AssetResponse:
    asset = session.get(Asset, asset_id)
    if asset is None:
        raise NotFound("素材不存在。")
    is_staff = bool(viewer and any(r in ADMIN_ROLE_RANK for r in viewer.roles))
    # Raises 404 rather than 403 for private assets, so the endpoint cannot be
    # used to probe for existence.
    media_service.signed_url_for(
        session,
        asset_id=asset_id,
        viewer_user_id=viewer.id if viewer else None,
        viewer_is_staff=is_staff,
    )
    return _asset_response(session, asset, viewer_id=viewer.id if viewer else None)


@router.get("/assets/{asset_id}/provenance", response_model=ProvenanceResponse)
def asset_provenance(asset_id: str, session: DbSession, viewer: OptionalUser) -> ProvenanceResponse:
    """Returns the AI disclosure claim attached to a generated asset."""
    is_staff = bool(viewer and any(r in ADMIN_ROLE_RANK for r in viewer.roles))
    media_service.signed_url_for(
        session,
        asset_id=asset_id,
        viewer_user_id=viewer.id if viewer else None,
        viewer_is_staff=is_staff,
    )
    manifest = media_service.provenance_for(session, asset_id)
    if manifest is None:
        raise NotFound("该素材没有溯源清单。")
    return ProvenanceResponse(
        asset_id=manifest.asset_id,
        generation_job_id=manifest.generation_job_id,
        claim=manifest.claim_json,
        signed=manifest.signature is not None,
    )


def _asset_response(session, asset: Asset, *, viewer_id: str | None) -> AssetResponse:  # type: ignore[no-untyped-def]
    return AssetResponse(
        id=asset.id,
        media_type=MediaType(asset.media_type),
        mime_type=asset.mime_type,
        size_bytes=asset.size_bytes,
        width=asset.width,
        height=asset.height,
        duration_ms=asset.duration_ms,
        url=media_urls.asset_url(session, asset.id),
        moderation_status=asset.moderation_status,
        is_prototype=asset.is_prototype,
        ai_generated=asset.role == AssetRole.GENERATION_OUTPUT,
    )
