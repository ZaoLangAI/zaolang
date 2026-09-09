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

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, text
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
    # `Operation` values this skill's template is meant for. Empty means "any
    # operation" — same convention as `AgentProfile.operations_json`
    # (`app/models/agent_skills.py`). A skill built around `duration_seconds`/
    # `video_options` should declare the video operations so it never gets
    # silently applied to a `text_to_image` job it was never written for.
    applicable_operations_json: Mapped[list[Any]] = mapped_column(default=list, nullable=False)
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
    # Integer credits to unlock. 0 = free. Only meaningful once published.
    access_credits: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    reject_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint("access_credits >= 0", name="access_credits_non_negative"),
        Index("ix_creation_skills_owner", "owner_user_id"),
        Index("ix_creation_skills_status_created", "status", "created_at"),
        # One character name per owner — scenes and templates may still share
        # a title with a character, and two owners may both have "林彻".
        Index(
            "uq_creation_skills_owner_character_title",
            "owner_user_id",
            "title",
            unique=True,
            postgresql_where=text("category = 'character'"),
        ),
    )
