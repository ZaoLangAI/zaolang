"""A card's management graph (P4): its looks / variants with their images,
the typed edges between them, and jobs still filling it — one read for the
`/create/{characters|scenes}/[id]` page."""

from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import Field

from app.api.schemas.asset_variants import (
    AssetVariantView,
    CameraPose,
    VariantAttributes,
    VariantPresets,
)
from app.api.schemas.character_voices import CharacterVoiceView
from app.api.schemas.common import ApiModel
from app.domain.asset_graph.derive import MAX_INSTRUCTION_LEN, DeriveOutput
from app.domain.asset_graph.service import MAX_EDGE_LABEL_LEN, MAX_RELATIONS_PER_EDGE
from app.domain.asset_variants.service import MAX_VARIANT_NAME_LEN
from app.domain.image_assets.camera import MAX_CAMERA_POSES
from app.domain.image_assets.vocabulary import MAX_CHARACTER_EXPRESSIONS, CharacterExpression
from app.models.enums import AssetEdgeOrigin, AssetGraphLevel, AssetRelation, QualityTier


class AssetEdgeView(ApiModel):
    id: str
    level: AssetGraphLevel
    source_id: str
    target_id: str
    relations: list[AssetRelation]
    label: str | None = None
    origin: AssetEdgeOrigin
    source_job_id: str | None = None
    created_at: dt.datetime | None = None


class AssetGraphCaps(ApiModel):
    """`None` = uncapped (a scene card's variants and total images)."""

    max_variants: int | None = None
    max_entries_per_variant: int
    max_entries: int | None = None
    max_edges: int
    max_voices: int | None = None


class AssetGraphPendingJob(ApiModel):
    """A generation job still filling this card (P6 fills it in)."""

    job_id: str
    status: str
    mode: str | None = None
    target_variant_id: str | None = None
    source_entry_id: str | None = None
    target_voice_id: str | None = None


class AssetGraphResponse(ApiModel):
    card_id: str
    card_kind: Literal["character", "scene", "prop"]
    name: str
    description: str | None = None
    # Characters: the card's 音色描述 (what 「AI 按描述匹配」 reads).
    voice_description: str | None = None
    anchor_entry_id: str | None = None
    variants: list[AssetVariantView] = Field(default_factory=list)
    edges: list[AssetEdgeView] = Field(default_factory=list)
    pending: list[AssetGraphPendingJob] = Field(default_factory=list)
    # A character's voices (P7); always empty for a scene.
    voices: list[CharacterVoiceView] = Field(default_factory=list)
    caps: AssetGraphCaps


class AssetEdgeCreateRequest(ApiModel):
    level: Literal["variant", "entry", "voice"]
    source_id: str = Field(max_length=40)
    target_id: str = Field(max_length=40)
    relations: list[AssetRelation] = Field(min_length=1, max_length=MAX_RELATIONS_PER_EDGE)
    label: str | None = Field(default=None, max_length=MAX_EDGE_LABEL_LEN)


class AssetEdgeUpdateRequest(ApiModel):
    """`label: null` leaves it; send `clear_label` to unset it."""

    relations: list[AssetRelation] | None = Field(
        default=None, min_length=1, max_length=MAX_RELATIONS_PER_EDGE
    )
    label: str | None = Field(default=None, max_length=MAX_EDGE_LABEL_LEN)
    clear_label: bool = False


# ---- adjust / derive (P6) --------------------------------------------------------


class AssetAdjustRequest(ApiModel):
    instruction: str = Field(min_length=1, max_length=MAX_INSTRUCTION_LEN)
    quality_tier: QualityTier = QualityTier.STANDARD
    aspect_ratio: str | None = Field(default=None, pattern=r"^\d{1,2}:\d{1,2}$")
    # `true` (the default) only prices; `false` submits one job.
    dry_run: bool = True


class AssetOrbitRequest(ApiModel):
    """多机位 (AC-2): re-draw the entry from each camera pose."""

    poses: list[CameraPose] = Field(min_length=1, max_length=MAX_CAMERA_POSES)
    quality_tier: QualityTier = QualityTier.STANDARD
    aspect_ratio: str | None = Field(default=None, pattern=r"^\d{1,2}:\d{1,2}$")
    # `true` (the default) only prices; `false` submits one job.
    dry_run: bool = True


class NewVariantDraftRequest(ApiModel):
    name: str = Field(min_length=1, max_length=MAX_VARIANT_NAME_LEN)
    description: str | None = Field(default=None, max_length=2000)
    presets: VariantPresets | None = None
    attributes: VariantAttributes | None = None
    scene_id: str | None = Field(default=None, max_length=40)
    scene_variant_id: str | None = Field(default=None, max_length=40)


class AssetDeriveRequest(ApiModel):
    """Exactly one of `target_variant_id` / `new_variant`."""

    output: DeriveOutput
    target_variant_id: str | None = Field(default=None, max_length=40)
    new_variant: NewVariantDraftRequest | None = None
    prompt_extra: str | None = Field(default=None, max_length=MAX_INSTRUCTION_LEN)
    expressions: list[CharacterExpression] | None = Field(
        default=None, min_length=1, max_length=MAX_CHARACTER_EXPRESSIONS
    )
    quality_tier: QualityTier = QualityTier.STANDARD
    aspect_ratio: str | None = Field(default=None, pattern=r"^\d{1,2}:\d{1,2}$")
    dry_run: bool = True


class AssetGenerateResponse(ApiModel):
    """The quote (like `quote:batch`), and on a submit what was created."""

    credits: int
    available_credits: int
    period_remaining: int | None = None
    within_spend_limit: bool
    sufficient: bool
    # Derive: what the look-level edge would say (source look → target look).
    relations: list[AssetRelation] = Field(default_factory=list)
    job_id: str | None = None
    variant_id: str | None = None
    edge_id: str | None = None
    replayed: bool = False
    # Orbit: the poses the job will draw, in pass order (a character sheet
    # source is led by the front single figure the others are drawn from).
    poses: list[CameraPose] = Field(default_factory=list)
