"""Curated system style catalogue.

Distinct from `StylePreset` (`app/models/works.py`): that is a user-owned,
instantly-public "save these params" shortcut derived from one work. A
`StyleGalleryEntry` is platform-curated — only back-office staff can write it
— always public, and carries a cover image plus localized labels so it can be
browsed as a picture in a grid, not just a name in a dropdown. The same rows
back both the studio's style-picker dialog and the create page's inspiration
section.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, id_column


class StyleGalleryEntry(Base, TimestampMixin):
    __tablename__ = "style_gallery_entries"

    id: Mapped[str] = id_column("stg")
    slug: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    label_zh: Mapped[str] = mapped_column(String(64), nullable=False)
    label_en: Mapped[str] = mapped_column(String(64), nullable=False)
    label_ja: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    cover_asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("assets.id", ondelete="SET NULL"), nullable=True
    )
    # Same shape as `StylePreset.params_json` / `ReusableParams` — applied onto
    # the studio form exactly like a preset (`aspect_ratio` / `prompt_suffix` /
    # `style_tags`, ...).
    params_json: Mapped[dict[str, Any]] = mapped_column(default=dict, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    apply_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    __table_args__ = (Index("ix_style_gallery_entries_active_sort", "is_active", "sort_order"),)
