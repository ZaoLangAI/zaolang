"""Reusable character profiles and the series that cast them.

A character exists so the same face and voice can be asked for again across
several episodes without the author retyping a description each time. A
series exists so those episodes can be told apart — it owns nothing about
generation itself, only the cast roster and the episode numbering that
`Work.series_id` / `Work.episode_number` point back at.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, id_column


class Character(Base, TimestampMixin):
    """A reusable cast member: a name, a look and a voice description.

    `reference_asset_ids_json` follows the same convention as
    `LineageEdge.reused_asset_ids_json` — a small, bounded list of asset ids
    stored as JSON rather than a join table, because nothing here needs to be
    queried from the asset side.
    """

    __tablename__ = "characters"

    id: Mapped[str] = id_column("chr")
    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    reference_asset_ids_json: Mapped[list[Any]] = mapped_column(default=list, nullable=False)
    # A text hint carried in generation params so a future TTS integration has
    # something to match against. No sample audio or cloning yet.
    voice_description: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (Index("ix_characters_owner_user_id", "owner_user_id"),)


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

    __table_args__ = (Index("ix_series_owner_user_id", "owner_user_id"),)
