"""Back-office CRUD for the curated system style catalogue.

Unlike `skill_library.py` (which only reviews/takes down user-authored
content), every `StyleGalleryEntry` is created here — there is no public
submission path, so full create/update/delete lives in this one file instead
of being split against a moderation queue.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.api.deps import DbSession
from app.api.schemas.admin import DangerousAction
from app.api.schemas.common import Page
from app.api.schemas.jobs import (
    AssetResponse,
    UploadCompleteRequest,
    UploadPresignRequest,
    UploadPresignResponse,
)
from app.api.schemas.style_gallery import (
    StyleGalleryEntryCreateRequest,
    StyleGalleryEntryResponse,
    StyleGalleryEntryUpdateRequest,
)
from app.api.v1.admin.deps import (
    AdminDangerous,
    AdminRead,
    AdminWrite,
    Operator,
    Viewer,
    require_confirmation,
)
from app.domain.audit import service as audit
from app.domain.errors import ValidationFailed
from app.domain.media import service as media_service
from app.domain.style_gallery import service as style_gallery
from app.models import StyleGalleryEntry
from app.models.enums import MediaType
from app.presenters import media_urls

router = APIRouter(tags=["admin:style-gallery"])

_COVER_PURPOSE = "style_gallery_cover"


@router.get("/style-gallery", response_model=Page[StyleGalleryEntryResponse])
def list_entries(session: DbSession, user: Viewer, _: AdminRead) -> Page[StyleGalleryEntryResponse]:
    entries = style_gallery.admin_list(session)
    return Page(items=[_response(session, entry) for entry in entries])


@router.post("/style-gallery", response_model=StyleGalleryEntryResponse, status_code=201)
def create_entry(
    payload: StyleGalleryEntryCreateRequest,
    request: Request,
    session: DbSession,
    user: Operator,
    _: AdminWrite,
) -> StyleGalleryEntryResponse:
    entry = style_gallery.create(
        session,
        slug=payload.slug,
        label_zh=payload.label_zh,
        label_en=payload.label_en,
        label_ja=payload.label_ja,
        description=payload.description,
        cover_asset_id=payload.cover_asset_id,
        params_json=payload.params,
        sort_order=payload.sort_order,
    )
    audit.record(
        session,
        actor=user,
        action="style_gallery.create",
        target_type="style_gallery_entry",
        target_id=entry.id,
        after={"slug": entry.slug, "label_zh": entry.label_zh},
        request=request,
    )
    session.commit()
    return _response(session, entry)


@router.put("/style-gallery/{entry_id}", response_model=StyleGalleryEntryResponse)
def update_entry(
    entry_id: str,
    payload: StyleGalleryEntryUpdateRequest,
    request: Request,
    session: DbSession,
    user: Operator,
    _: AdminWrite,
) -> StyleGalleryEntryResponse:
    entry = style_gallery.get(session, entry_id=entry_id)
    before = {"label_zh": entry.label_zh, "is_active": entry.is_active}
    style_gallery.update(
        session,
        entry=entry,
        label_zh=payload.label_zh,
        label_en=payload.label_en,
        label_ja=payload.label_ja,
        description=payload.description,
        cover_asset_id=payload.cover_asset_id,
        params_json=payload.params,
        sort_order=payload.sort_order,
        is_active=payload.is_active,
    )
    audit.record(
        session,
        actor=user,
        action="style_gallery.update",
        target_type="style_gallery_entry",
        target_id=entry.id,
        before=before,
        after={"label_zh": entry.label_zh, "is_active": entry.is_active},
        request=request,
    )
    session.commit()
    return _response(session, entry)


@router.post("/style-gallery/{entry_id}/delete", response_model=Page[StyleGalleryEntryResponse])
def delete_entry(
    entry_id: str,
    payload: DangerousAction,
    request: Request,
    session: DbSession,
    user: Operator,
    _: AdminDangerous,
) -> Page[StyleGalleryEntryResponse]:
    """Permanent removal — turning an entry off without deleting it is
    `update(is_active=False)`, which is the reversible everyday action."""
    require_confirmation(payload.confirm)
    entry = style_gallery.get(session, entry_id=entry_id)
    before = {"slug": entry.slug, "label_zh": entry.label_zh}
    style_gallery.delete(session, entry=entry)
    audit.record(
        session,
        actor=user,
        action="style_gallery.delete",
        target_type="style_gallery_entry",
        target_id=entry_id,
        before=before,
        reason=payload.reason,
        request=request,
    )
    session.commit()
    entries = style_gallery.admin_list(session)
    return Page(items=[_response(session, entry) for entry in entries])


@router.post("/style-gallery/uploads/presign", response_model=UploadPresignResponse)
def presign_cover_upload(
    payload: UploadPresignRequest, session: DbSession, user: Operator, _: AdminWrite
) -> UploadPresignResponse:
    if payload.purpose != _COVER_PURPOSE:
        raise ValidationFailed("该接口仅用于画风封面上传。", purpose=payload.purpose)
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


@router.post("/style-gallery/uploads/complete", response_model=AssetResponse, status_code=201)
def complete_cover_upload(
    payload: UploadCompleteRequest, session: DbSession, user: Operator, _: AdminWrite
) -> AssetResponse:
    asset = media_service.complete_upload(
        session, user_id=user.id, upload_session_id=payload.upload_session_id
    )
    session.commit()
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
        ai_generated=False,
    )


def _response(session: DbSession, entry: StyleGalleryEntry) -> StyleGalleryEntryResponse:
    return StyleGalleryEntryResponse(
        id=entry.id,
        slug=entry.slug,
        label_zh=entry.label_zh,
        label_en=entry.label_en,
        label_ja=entry.label_ja,
        description=entry.description,
        cover_asset_id=entry.cover_asset_id,
        cover_url=media_urls.asset_url(session, entry.cover_asset_id),
        params=entry.params_json,
        sort_order=entry.sort_order,
        is_active=entry.is_active,
        apply_count=entry.apply_count,
        created_at=entry.created_at,
    )
