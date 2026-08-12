"""Curated system style catalogue: admin writes, everyone reads.

Every entry is platform-curated — there is no owner-scoped visibility to
enforce, unlike `StylePreset`. The two read paths differ only in which rows
they see: the public studio picker and the create page's inspiration section
both use `list_active()`; the back office uses `admin_list()` to also see
entries an operator has turned off.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.errors import Conflict, NotFound
from app.models import StyleGalleryEntry


def list_active(session: Session, *, limit: int = 60) -> list[StyleGalleryEntry]:
    stmt = (
        select(StyleGalleryEntry)
        .where(StyleGalleryEntry.is_active.is_(True))
        .order_by(StyleGalleryEntry.sort_order, StyleGalleryEntry.created_at)
        .limit(limit)
    )
    return list(session.scalars(stmt))


def admin_list(session: Session, *, limit: int = 200) -> list[StyleGalleryEntry]:
    stmt = (
        select(StyleGalleryEntry)
        .order_by(StyleGalleryEntry.sort_order, StyleGalleryEntry.created_at)
        .limit(limit)
    )
    return list(session.scalars(stmt))


def get(session: Session, *, entry_id: str) -> StyleGalleryEntry:
    entry = session.get(StyleGalleryEntry, entry_id)
    if entry is None:
        raise NotFound("画风不存在。")
    return entry


def get_usable(session: Session, *, entry_id: str) -> StyleGalleryEntry:
    """Only an active entry can be applied — an operator turning one off is
    meant to pull it out of circulation immediately, not just off the list."""
    entry = get(session, entry_id=entry_id)
    if not entry.is_active:
        raise NotFound("画风不存在。")
    return entry


def create(
    session: Session,
    *,
    slug: str,
    label_zh: str,
    label_en: str,
    label_ja: str,
    description: str | None,
    cover_asset_id: str | None,
    params_json: dict[str, Any],
    sort_order: int,
) -> StyleGalleryEntry:
    if session.scalar(select(StyleGalleryEntry).where(StyleGalleryEntry.slug == slug)) is not None:
        raise Conflict(f"标识 {slug} 已被使用。")
    entry = StyleGalleryEntry(
        slug=slug,
        label_zh=label_zh,
        label_en=label_en,
        label_ja=label_ja,
        description=description,
        cover_asset_id=cover_asset_id,
        params_json=params_json,
        sort_order=sort_order,
    )
    session.add(entry)
    session.flush()
    return entry


def update(
    session: Session,
    *,
    entry: StyleGalleryEntry,
    label_zh: str,
    label_en: str,
    label_ja: str,
    description: str | None,
    cover_asset_id: str | None,
    params_json: dict[str, Any],
    sort_order: int,
    is_active: bool,
) -> StyleGalleryEntry:
    entry.label_zh = label_zh
    entry.label_en = label_en
    entry.label_ja = label_ja
    entry.description = description
    entry.cover_asset_id = cover_asset_id
    entry.params_json = params_json
    entry.sort_order = sort_order
    entry.is_active = is_active
    session.flush()
    return entry


def delete(session: Session, *, entry: StyleGalleryEntry) -> None:
    session.delete(entry)
    session.flush()


def apply(session: Session, *, entry_id: str) -> StyleGalleryEntry:
    entry = get_usable(session, entry_id=entry_id)
    entry.apply_count += 1
    session.flush()
    return entry
