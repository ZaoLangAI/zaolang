"""The series that cast reusable characters.

A character used to be its own `Character` table here. It is now stored as a
`CreationSkill` with `category=CHARACTER` (see `app.domain.characters.service`,
which is a thin adapter over `app.domain.skill_library.service`) so that a
cast member gets the skill library's draft/review/publish/marketplace
lifecycle for free — a creator can share or sell a character design the same
way they share any other creation skill. `Series.character_ids_json` holds
`CreationSkill.id` values, not a foreign key to a dropped table (same
"small, bounded JSON list, not a join table" convention as everywhere else
in this module).

A series exists so episodes can be told apart — it owns nothing about
generation itself, only the cast roster and the episode numbering that
`Work.series_id` / `Work.episode_number` point back at.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, id_column


class Series(Base, TimestampMixin):
    """A named cast roster that episodes (`Work` rows) are numbered under."""

    __tablename__ = "series"

    id: Mapped[str] = id_column("ser")
    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    shortform_profile_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    character_ids_json: Mapped[list[Any]] = mapped_column(default=list, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), default="cast", nullable=False)
    default_locale: Mapped[str] = mapped_column(String(16), default="zh-CN", nullable=False)
    brand_pack_asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("assets.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False)
    allow_external_models: Mapped[bool] = mapped_column(default=False, nullable=False)

    # `kind=drama` short-drama management metadata (剧集管理). Left null/empty
    # for `kind=cast` rows — these fields only mean something for a
    # production project, not a character roster.
    english_title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    planned_episode_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    genre_tags_json: Mapped[list[Any]] = mapped_column(
        default=list, server_default="[]", nullable=False
    )
    target_platforms_json: Mapped[list[Any]] = mapped_column(
        default=list, server_default="[]", nullable=False
    )
    logo_asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("assets.id", ondelete="SET NULL"), nullable=True
    )
    # `status=trashed` recycle bin timestamp — mirrors `Work.trashed_at`.
    # Null unless the series is currently trashed.
    trashed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_series_owner_user_id", "owner_user_id"),
        Index("ix_series_owner_user_id_kind", "owner_user_id", "kind"),
    )
