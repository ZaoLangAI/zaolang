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
        # A look also points at a scene card (`scene_skill_id`); only
        # `skill_id` is ownership.
        foreign_keys="SkillAssetVariant.skill_id",
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
    # look: `{age_stage?, period?}`. Enumerated values only — write-back and
    # the scene matrix match on it exactly. Copy before mutating (JSONB
    # identity tracking).
    presets_json: Mapped[dict[str, Any]] = mapped_column(
        default=dict, server_default=text("'{}'::jsonb"), nullable=False
    )
    # Free text (P3): look `{outfit?, state?, scene_note?, custom: [{key,
    # value}]}`, scene variant `{custom}` — `asset_variants.service._check_attributes`.
    attributes_json: Mapped[dict[str, Any]] = mapped_column(
        default=dict, server_default=text("'{}'::jsonb"), nullable=False
    )
    # A look set in one of the owner's scene cards (and optionally one of its
    # variants). Cleared when that card / variant goes.
    scene_skill_id: Mapped[str | None] = mapped_column(
        ForeignKey("creation_skills.id", ondelete="SET NULL"), nullable=True
    )
    scene_variant_id: Mapped[str | None] = mapped_column(
        ForeignKey("skill_asset_variants.id", ondelete="SET NULL"), nullable=True
    )
    # The voice this look speaks with (P7) — one of the same card's
    # `character_voices` (checked by the domain).
    voice_id: Mapped[str | None] = mapped_column(
        ForeignKey("character_voices.id", ondelete="SET NULL"), nullable=True
    )
    is_default: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)

    skill: Mapped[CreationSkill] = relationship(
        back_populates="asset_variants", foreign_keys=[skill_id]
    )
    entries: Mapped[list[SkillAssetEntry]] = relationship(
        back_populates="variant",
        cascade="all, delete-orphan",
        passive_deletes=True,
        foreign_keys="[SkillAssetEntry.variant_id, SkillAssetEntry.skill_id]",
        order_by="(SkillAssetEntry.sort_order, SkillAssetEntry.created_at)",
    )

    __table_args__ = (
        CheckConstraint(f"kind IN ({_VARIANT_KINDS})", name="kind_valid"),
        CheckConstraint(
            "kind = 'look' OR (scene_skill_id IS NULL AND scene_variant_id IS NULL)",
            name="scene_link_look_only",
        ),
        CheckConstraint("kind = 'look' OR voice_id IS NULL", name="voice_look_only"),
        UniqueConstraint("skill_id", "name", name="uq_skill_asset_variants_skill_id_name"),
        # Target of `skill_asset_entries`' composite FK: an entry's variant
        # must belong to the same skill the entry says it does.
        UniqueConstraint("id", "skill_id", name="uq_skill_asset_variants_id_skill_id"),
        Index("ix_skill_asset_variants_skill_id", "skill_id"),
        Index("ix_skill_asset_variants_scene_skill_id", "scene_skill_id"),
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
    # The camera pose a multi-angle image was drawn from (AC-2):
    # `{azimuth, elevation, distance}` on `image_assets.camera`'s grid. `None`
    # for most entries — readers fall back to `view` (`camera.from_view`).
    camera_json: Mapped[dict[str, Any] | None] = mapped_column(nullable=True)
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
        # Target of `skill_asset_edges`' composite FKs.
        UniqueConstraint("id", "skill_id", name="uq_skill_asset_entries_id_skill_id"),
        Index("ix_skill_asset_entries_skill", "skill_id", "variant_id", "sort_order"),
        Index("ix_skill_asset_entries_asset_id", "asset_id"),
        Index(
            "uq_skill_asset_entries_anchor",
            "skill_id",
            unique=True,
            postgresql_where=text("is_anchor"),
        ),
    )


_EDGE_LEVEL_SHAPE = (
    "(level = 'variant' AND source_variant_id IS NOT NULL AND target_variant_id IS NOT NULL"
    " AND source_entry_id IS NULL AND target_entry_id IS NULL"
    " AND source_voice_id IS NULL AND target_voice_id IS NULL"
    " AND source_variant_id <> target_variant_id)"
    " OR (level = 'entry' AND source_entry_id IS NOT NULL AND target_entry_id IS NOT NULL"
    " AND source_variant_id IS NULL AND target_variant_id IS NULL"
    " AND source_voice_id IS NULL AND target_voice_id IS NULL"
    " AND source_entry_id <> target_entry_id)"
    " OR (level = 'voice' AND source_voice_id IS NOT NULL AND target_voice_id IS NOT NULL"
    " AND source_variant_id IS NULL AND target_variant_id IS NULL"
    " AND source_entry_id IS NULL AND target_entry_id IS NULL"
    " AND source_voice_id <> target_voice_id)"
)


class SkillAssetEdge(Base, TimestampMixin):
    """A typed, directed relation between two looks / variants or two images
    of one card (P4): "老年 ← 青年 by age", "this sheet was adjusted from that
    one". Owner-only graph metadata — never published, never moderated
    content. Both ends CASCADE; acyclicity is the domain's job
    (`asset_graph.service.add_edge`)."""

    __tablename__ = "skill_asset_edges"

    id: Mapped[str] = id_column("sae")
    skill_id: Mapped[str] = mapped_column(
        ForeignKey("creation_skills.id", ondelete="CASCADE"), nullable=False
    )
    level: Mapped[str] = mapped_column(String(8), nullable=False)
    source_variant_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    target_variant_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    source_entry_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    target_entry_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    source_voice_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    target_voice_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # `AssetRelation` values, at least one.
    relations_json: Mapped[list[Any]] = mapped_column(
        default=list, server_default=text("'[]'::jsonb"), nullable=False
    )
    label: Mapped[str | None] = mapped_column(String(40), nullable=True)
    origin: Mapped[str] = mapped_column(String(8), nullable=False)
    # Trace only (DM invariant 12).
    source_job_id: Mapped[str | None] = mapped_column(String(40), nullable=True)

    __table_args__ = (
        CheckConstraint("level IN ('variant', 'entry', 'voice')", name="level_valid"),
        CheckConstraint("origin IN ('auto', 'manual')", name="origin_valid"),
        CheckConstraint(_EDGE_LEVEL_SHAPE, name="level_shape"),
        ForeignKeyConstraint(
            ["source_variant_id", "skill_id"],
            ["skill_asset_variants.id", "skill_asset_variants.skill_id"],
            ondelete="CASCADE",
            name="fk_skill_asset_edges_source_variant",
        ),
        ForeignKeyConstraint(
            ["target_variant_id", "skill_id"],
            ["skill_asset_variants.id", "skill_asset_variants.skill_id"],
            ondelete="CASCADE",
            name="fk_skill_asset_edges_target_variant",
        ),
        ForeignKeyConstraint(
            ["source_entry_id", "skill_id"],
            ["skill_asset_entries.id", "skill_asset_entries.skill_id"],
            ondelete="CASCADE",
            name="fk_skill_asset_edges_source_entry",
        ),
        ForeignKeyConstraint(
            ["target_entry_id", "skill_id"],
            ["skill_asset_entries.id", "skill_asset_entries.skill_id"],
            ondelete="CASCADE",
            name="fk_skill_asset_edges_target_entry",
        ),
        ForeignKeyConstraint(
            ["source_voice_id", "skill_id"],
            ["character_voices.id", "character_voices.skill_id"],
            ondelete="CASCADE",
            name="fk_skill_asset_edges_source_voice",
        ),
        ForeignKeyConstraint(
            ["target_voice_id", "skill_id"],
            ["character_voices.id", "character_voices.skill_id"],
            ondelete="CASCADE",
            name="fk_skill_asset_edges_target_voice",
        ),
        Index("ix_skill_asset_edges_skill_level", "skill_id", "level"),
        Index(
            "uq_skill_asset_edges_variant_pair",
            "source_variant_id",
            "target_variant_id",
            unique=True,
            postgresql_where=text("level = 'variant'"),
        ),
        Index(
            "uq_skill_asset_edges_voice_pair",
            "source_voice_id",
            "target_voice_id",
            unique=True,
            postgresql_where=text("level = 'voice'"),
        ),
        Index(
            "uq_skill_asset_edges_entry_pair",
            "source_entry_id",
            "target_entry_id",
            unique=True,
            postgresql_where=text("level = 'entry'"),
        ),
    )


class CharacterVoice(Base, TimestampMixin):
    """One voice of a character card (P7): a TTS model's preset voice with
    its parameters, or a cloned sample. Owner-only like the graph — never
    part of a published card. One default per card; looks bind to a voice
    (`SkillAssetVariant.voice_id`). `characters.voices` owns the rules."""

    __tablename__ = "character_voices"

    id: Mapped[str] = id_column("chv")
    skill_id: Mapped[str] = mapped_column(
        ForeignKey("creation_skills.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(40), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(8), nullable=False)
    # The TTS model a preset voice belongs to (`forced_model` at submit);
    # optional for a clone (routing picks a clone-capable model).
    model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    voice: Mapped[str | None] = mapped_column(String(60), nullable=True)
    # `{speed?, emotion?}` — only what the model takes
    # (`model_catalog.voice_capabilities`).
    params_json: Mapped[dict[str, Any]] = mapped_column(
        default=dict, server_default=text("'{}'::jsonb"), nullable=False
    )
    # `{age_stage?, emotion?, use?, custom: [{key, value}]}`.
    attributes_json: Mapped[dict[str, Any]] = mapped_column(
        default=dict, server_default=text("'{}'::jsonb"), nullable=False
    )
    sample_asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("assets.id", ondelete="SET NULL"), nullable=True
    )
    preview_asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("assets.id", ondelete="SET NULL"), nullable=True
    )
    preview_text: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Trace only (DM invariant 12).
    preview_job_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    is_default: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)

    __table_args__ = (
        CheckConstraint("source IN ('preset', 'clone')", name="source_valid"),
        CheckConstraint(
            "source <> 'preset' OR (model IS NOT NULL AND voice IS NOT NULL)",
            name="preset_has_voice",
        ),
        UniqueConstraint("skill_id", "name", name="uq_character_voices_skill_id_name"),
        # Target of `skill_asset_edges`' voice-pair composite FKs.
        UniqueConstraint("id", "skill_id", name="uq_character_voices_id_skill_id"),
        Index("ix_character_voices_skill_id", "skill_id"),
        Index(
            "uq_character_voices_default",
            "skill_id",
            unique=True,
            postgresql_where=text("is_default"),
        ),
    )
