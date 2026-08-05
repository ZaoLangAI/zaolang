"""User-authored generation parameter templates, shareable after review.

Distinct from `StylePreset` (`app/models/works.py`): that is a lightweight,
instantly-public "save these params" shortcut with no moderation gate. A
`CreationSkill` is the curated, discoverable version — it always starts
private (`DRAFT`) so the owner can use it in their own creations right away,
and only enters `moderation_queue_items` (subject_type `"skill"`) once the
owner explicitly asks to share it via `publish()`.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, id_column
from app.models.enums import CreationSkillCategory, CreationSkillStatus, CreationSkillVisibility


class CreationSkill(Base, TimestampMixin):
    __tablename__ = "creation_skills"

    id: Mapped[str] = id_column("sk")
    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str] = mapped_column(String(300), default="", nullable=False)
    category: Mapped[str] = mapped_column(
        String(24), default=CreationSkillCategory.OTHER, nullable=False
    )
    # Same shape as `StylePreset.params_json` / `ReusableParams` — a generation
    # parameter template, not free-form data.
    params_json: Mapped[dict[str, Any]] = mapped_column(default=dict, nullable=False)
    cover_asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("assets.id", ondelete="SET NULL"), nullable=True
    )
    visibility: Mapped[str] = mapped_column(
        String(16), default=CreationSkillVisibility.PRIVATE, nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(24), default=CreationSkillStatus.DRAFT, nullable=False
    )
    usage_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reject_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_creation_skills_owner", "owner_user_id"),
        Index("ix_creation_skills_status_created", "status", "created_at"),
    )
