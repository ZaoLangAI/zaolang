"""`app.domain.style_gallery`: curated catalogue reads and writes."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.domain.errors import Conflict, NotFound
from app.domain.style_gallery import service as style_gallery


def _create(session: Session, *, slug: str = "anime-japanese", sort_order: int = 0):
    return style_gallery.create(
        session,
        slug=slug,
        label_zh="日漫",
        label_en="Japanese anime",
        label_ja="日本アニメ",
        description="赛璐璐渲染。",
        cover_asset_id=None,
        params_json={"aspect_ratio": "9:16", "prompt_suffix": "anime style"},
        sort_order=sort_order,
    )


def test_create_then_get(db: Session) -> None:
    entry = _create(db)
    fetched = style_gallery.get(db, entry_id=entry.id)
    assert fetched.slug == "anime-japanese"
    assert fetched.is_active is True
    assert fetched.apply_count == 0


def test_duplicate_slug_is_rejected(db: Session) -> None:
    _create(db, slug="dup")
    with pytest.raises(Conflict):
        _create(db, slug="dup")


def test_list_active_excludes_disabled_entries(db: Session) -> None:
    visible = _create(db, slug="visible")
    hidden = _create(db, slug="hidden")
    style_gallery.update(
        db,
        entry=hidden,
        label_zh=hidden.label_zh,
        label_en=hidden.label_en,
        label_ja=hidden.label_ja,
        description=hidden.description,
        cover_asset_id=None,
        params_json=hidden.params_json,
        sort_order=hidden.sort_order,
        is_active=False,
    )

    active_ids = {e.id for e in style_gallery.list_active(db)}
    assert visible.id in active_ids
    assert hidden.id not in active_ids

    admin_ids = {e.id for e in style_gallery.admin_list(db)}
    assert {visible.id, hidden.id} <= admin_ids


def test_apply_bumps_the_counter_and_returns_params(db: Session) -> None:
    entry = _create(db)
    applied = style_gallery.apply(db, entry_id=entry.id)
    assert applied.apply_count == 1
    assert applied.params_json["aspect_ratio"] == "9:16"


def test_applying_a_disabled_entry_is_not_found(db: Session) -> None:
    entry = _create(db)
    style_gallery.update(
        db,
        entry=entry,
        label_zh=entry.label_zh,
        label_en=entry.label_en,
        label_ja=entry.label_ja,
        description=entry.description,
        cover_asset_id=None,
        params_json=entry.params_json,
        sort_order=entry.sort_order,
        is_active=False,
    )
    with pytest.raises(NotFound):
        style_gallery.apply(db, entry_id=entry.id)


def test_delete_removes_the_row(db: Session) -> None:
    entry = _create(db)
    style_gallery.delete(db, entry=entry)
    with pytest.raises(NotFound):
        style_gallery.get(db, entry_id=entry.id)
