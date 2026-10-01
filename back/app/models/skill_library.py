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

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, id_column, utcnow
from app.models.enums import (
    AssetEntryStatus,
    AssetEntryType,
    AssetVariantKind,
    CreationSkillCategory,
    CreationSkillStatus,
    CreationSkillVisibility,
)


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

    # Character looks / scene variants and their images
    # (`app.domain.asset_variants`). Database-level CASCADE deletes them with
    # the skill (`skill_library.service.delete` is a hard delete).
    asset_variants: Mapped[list[SkillAssetVariant]] = relationship(
        back_populates="skill",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="(SkillAssetVariant.is_default.desc(), SkillAssetVariant.sort_order, "
        "SkillAssetVariant.created_at)",
    )

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


_VARIANT_KINDS = ", ".join(f"'{kind.value}'" for kind in AssetVariantKind)
_ENTRY_TYPES = ", ".join(f"'{kind.value}'" for kind in AssetEntryType)
_ENTRY_STATUSES = ", ".join(f"'{kind.value}'" for kind in AssetEntryStatus)


class SkillAssetVariant(Base, TimestampMixin):
    """One character look (造型) or scene variant (变体) inside a
    character/scene `CreationSkill`. Not separately published or sold: it
    lives and dies with its card. Exactly one per skill is the default."""

    __tablename__ = "skill_asset_variants"

    id: Mapped[str] = id_column("skv")
    skill_id: Mapped[str] = mapped_column(
        ForeignKey("creation_skills.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(40), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Scene: `{lighting, weather, state, period}` (`image_assets.vocabulary`);
    # look: `{age_stage?}`. Copy before mutating (JSONB identity tracking).
    presets_json: Mapped[dict[str, Any]] = mapped_column(
        default=dict, server_default=text("'{}'::jsonb"), nullable=False
    )
    is_default: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)

    skill: Mapped[CreationSkill] = relationship(back_populates="asset_variants")
    entries: Mapped[list[SkillAssetEntry]] = relationship(
        back_populates="variant",
        cascade="all, delete-orphan",
        passive_deletes=True,
        foreign_keys="[SkillAssetEntry.variant_id, SkillAssetEntry.skill_id]",
        order_by="(SkillAssetEntry.sort_order, SkillAssetEntry.created_at)",
    )

    __table_args__ = (
        CheckConstraint(f"kind IN ({_VARIANT_KINDS})", name="kind_valid"),
        UniqueConstraint("skill_id", "name", name="uq_skill_asset_variants_skill_id_name"),
        # Target of `skill_asset_entries`' composite FK: an entry's variant
        # must belong to the same skill the entry says it does.
        UniqueConstraint("id", "skill_id", name="uq_skill_asset_variants_id_skill_id"),
        Index("ix_skill_asset_variants_skill_id", "skill_id"),
        Index(
            "uq_skill_asset_variants_default",
            "skill_id",
            unique=True,
            postgresql_where=text("is_default"),
        ),
    )


class SkillAssetEntry(Base):
    """One reference image (or clip) filed under a look/variant."""

    __tablename__ = "skill_asset_entries"

    id: Mapped[str] = id_column("ske")
    variant_id: Mapped[str] = mapped_column(String(40), nullable=False)
    # Denormalised from the variant (enforced by the composite FK) so the
    # one-anchor-per-skill index and per-skill reads need no join.
    skill_id: Mapped[str] = mapped_column(String(40), nullable=False)
    asset_id: Mapped[str] = mapped_column(
        ForeignKey("assets.id", ondelete="CASCADE"), nullable=False
    )
    entry_type: Mapped[str] = mapped_column(String(24), nullable=False)
    view: Mapped[str | None] = mapped_column(String(16), nullable=True)
    expressions_json: Mapped[list[Any] | None] = mapped_column(nullable=True)
    label: Mapped[str | None] = mapped_column(String(60), nullable=True)
    status: Mapped[str] = mapped_column(
        String(12),
        default=AssetEntryStatus.APPROVED,
        server_default=AssetEntryStatus.APPROVED.value,
        nullable=False,
    )
    is_anchor: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
    # Trace only — the job may be cleaned up first (DM invariant 12).
    source_job_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    variant: Mapped[SkillAssetVariant] = relationship(
        back_populates="entries", foreign_keys=[variant_id, skill_id]
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["variant_id", "skill_id"],
            ["skill_asset_variants.id", "skill_asset_variants.skill_id"],
            ondelete="CASCADE",
            name="fk_skill_asset_entries_variant_id_skill_asset_variants",
        ),
        CheckConstraint(f"entry_type IN ({_ENTRY_TYPES})", name="entry_type_valid"),
        CheckConstraint(f"status IN ({_ENTRY_STATUSES})", name="status_valid"),
        UniqueConstraint(
            "variant_id", "asset_id", name="uq_skill_asset_entries_variant_id_asset_id"
        ),
        Index("ix_skill_asset_entries_skill", "skill_id", "variant_id", "sort_order"),
        Index("ix_skill_asset_entries_asset_id", "asset_id"),
        Index(
            "uq_skill_asset_entries_anchor",
            "skill_id",
            unique=True,
            postgresql_where=text("is_anchor"),
        ),
    )
