"""Curated system style catalogue: public read, `/apply` usage counter.

Backs two surfaces with one dataset — the studio's style-picker dialog and the
create page's inspiration section (`app/domain/style_gallery/service.py`).
Writing is back-office only, see `app/api/v1/admin/style_gallery.py`.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import CurrentUser, DbSession
from app.api.schemas.common import Page
from app.api.schemas.style_gallery import StyleGalleryEntryResponse
from app.domain.style_gallery import service as style_gallery
from app.models import StyleGalleryEntry
from app.presenters import media_urls

router = APIRouter(tags=["style-gallery"])


@router.get("/style-gallery", response_model=Page[StyleGalleryEntryResponse])
def list_style_gallery(session: DbSession) -> Page[StyleGalleryEntryResponse]:
    entries = style_gallery.list_active(session)
    return Page(items=[_response(session, entry) for entry in entries])


@router.get("/style-gallery/{entry_id}", response_model=StyleGalleryEntryResponse)
def get_style_gallery_entry(entry_id: str, session: DbSession) -> StyleGalleryEntryResponse:
    entry = style_gallery.get_usable(session, entry_id=entry_id)
    return _response(session, entry)


@router.post("/style-gallery/{entry_id}/apply", response_model=StyleGalleryEntryResponse)
def apply_style_gallery_entry(
    entry_id: str, user: CurrentUser, session: DbSession
) -> StyleGalleryEntryResponse:
    entry = style_gallery.apply(session, entry_id=entry_id)
    session.commit()
    return _response(session, entry)


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
