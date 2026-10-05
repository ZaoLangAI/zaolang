"""Character looks / scene variants and their images (P1, see
`docs/asset-variants-p1.md`). Shared by `/v1/characters/{id}/looks…` and
`/v1/scenes/{id}/variants…`."""

from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from pydantic import Field

from app.api.schemas.common import ApiModel
from app.domain.asset_variants.service import (
    LOOK_ATTRIBUTE_LIMITS,
    MAX_CUSTOM_ATTRIBUTES,
    MAX_CUSTOM_KEY_LEN,
    MAX_CUSTOM_VALUE_LEN,
    MAX_VARIANT_NAME_LEN,
)
from app.domain.image_assets.vocabulary import (
    MAX_CHARACTER_EXPRESSIONS,
    AgeStage,
    CharacterExpression,
    SceneLighting,
    ScenePeriod,
    SceneState,
    SceneWeather,
)
from app.models.enums import AssetEntryStatus, AssetEntryType, QualityTier

# `GET /v1/characters` / `/v1/scenes`: `summary` leaves out `looks` /
# `variants` (every image of every card, each a signed URL) for list pages
# that only show a card's hero and text. Pickers that choose a look keep `full`.
LibraryListView = Literal["full", "summary"]


class VariantPresets(ApiModel):
    """Scene variant presets (P0 vocabulary) or a look's `age_stage` (P2-6).
    The service rejects the other kind's keys (a look has no lighting, a
    scene variant no age)."""

    lighting: SceneLighting | None = None
    weather: SceneWeather | None = None
    state: SceneState | None = None
    period: ScenePeriod | None = None
    age_stage: AgeStage | None = None


class CustomAttribute(ApiModel):
    key: str = Field(max_length=MAX_CUSTOM_KEY_LEN)
    value: str = Field(max_length=MAX_CUSTOM_VALUE_LEN)


class VariantAttributes(ApiModel):
    """Free-text look attributes (P3) — each becomes a prompt sentence. A
    scene variant takes only `custom` (the service rejects the rest)."""

    outfit: str | None = Field(default=None, max_length=LOOK_ATTRIBUTE_LIMITS["outfit"])
    state: str | None = Field(default=None, max_length=LOOK_ATTRIBUTE_LIMITS["state"])
    scene_note: str | None = Field(default=None, max_length=LOOK_ATTRIBUTE_LIMITS["scene_note"])
    custom: list[CustomAttribute] = Field(default_factory=list, max_length=MAX_CUSTOM_ATTRIBUTES)


class SceneLinkView(ApiModel):
    """The scene card a look is set in (owner's own editor only)."""

    scene_id: str
    scene_name: str
    variant_id: str | None = None
    variant_name: str | None = None
    thumb_url: str | None = None


class AssetEntryView(ApiModel):
    id: str
    asset_id: str
    url: str | None = None
    entry_type: AssetEntryType
    view: str | None = None
    expressions: list[str] = Field(default_factory=list)
    label: str | None = None
    status: AssetEntryStatus
    is_anchor: bool = False
    source_job_id: str | None = None
    created_at: dt.datetime | None = None


class AssetVariantView(ApiModel):
    id: str
    name: str
    description: str | None = None
    presets: dict[str, Any] = Field(default_factory=dict)
    attributes: VariantAttributes = Field(default_factory=VariantAttributes)
    # Owner-only: an unlocked marketplace card never shows it.
    scene_link: SceneLinkView | None = None
    # The character voice this look speaks with (owner-only, P7).
    voice_id: str | None = None
    is_default: bool
    sort_order: int
    entries: list[AssetEntryView] = Field(default_factory=list)


class AssetVariantCreateRequest(ApiModel):
    name: str = Field(min_length=1, max_length=MAX_VARIANT_NAME_LEN)
    description: str | None = Field(default=None, max_length=2000)
    presets: VariantPresets | None = None
    attributes: VariantAttributes | None = None
    scene_id: str | None = Field(default=None, max_length=40)
    scene_variant_id: str | None = Field(default=None, max_length=40)


class AssetVariantUpdateRequest(ApiModel):
    """`attributes` replaces the whole set; `scene_id: null` leaves the link
    as is — send `clear_scene` to unset it."""

    name: str | None = Field(default=None, min_length=1, max_length=MAX_VARIANT_NAME_LEN)
    description: str | None = Field(default=None, max_length=2000)
    presets: VariantPresets | None = None
    attributes: VariantAttributes | None = None
    scene_id: str | None = Field(default=None, max_length=40)
    scene_variant_id: str | None = Field(default=None, max_length=40)
    clear_scene: bool = False
    # A look's voice (P7); `clear_voice` unbinds it.
    voice_id: str | None = Field(default=None, max_length=40)
    clear_voice: bool = False
    sort_order: int | None = Field(default=None, ge=0, le=1000)
    make_default: bool = False


class AssetEntryCreateRequest(ApiModel):
    asset_id: str = Field(max_length=40)
    entry_type: AssetEntryType
    view: str | None = Field(default=None, max_length=16)
    expressions: list[CharacterExpression] | None = Field(
        default=None, max_length=MAX_CHARACTER_EXPRESSIONS
    )
    label: str | None = Field(default=None, max_length=60)


class AssetEntryUpdateRequest(ApiModel):
    """`view: null` is "leave as is"; send `clear_view` to unset it."""

    variant_id: str | None = Field(default=None, max_length=40)
    entry_type: AssetEntryType | None = None
    view: str | None = Field(default=None, max_length=16)
    clear_view: bool = False
    expressions: list[CharacterExpression] | None = Field(
        default=None, max_length=MAX_CHARACTER_EXPRESSIONS
    )
    label: str | None = Field(default=None, max_length=60)
    status: AssetEntryStatus | None = None


# ---- scene variant matrix (P2-5) ------------------------------------------------


class SceneMatrixAxes(ApiModel):
    """The values picked per axis; their cartesian product is the matrix
    (≤4 per axis, ≤12 cells per request — `scenes.matrix`)."""

    lighting: list[SceneLighting] = Field(default_factory=list, max_length=4)
    weather: list[SceneWeather] = Field(default_factory=list, max_length=4)
    state: list[SceneState] = Field(default_factory=list, max_length=4)
    period: list[ScenePeriod] = Field(default_factory=list, max_length=4)


class SceneMatrixRequest(ApiModel):
    axes: SceneMatrixAxes
    quality_tier: QualityTier = QualityTier.STANDARD
    aspect_ratio: str = Field(default="16:9", max_length=16)
    # Defaults to the card's own name + description.
    prompt: str | None = Field(default=None, max_length=4096)
    # `true` (the default) only plans and prices; `false` submits one job
    # per new cell.
    dry_run: bool = True


class SceneMatrixCellView(ApiModel):
    presets: dict[str, str]
    label: str
    # `new` is generated; `exists` (approved master) and `candidate` (only
    # unapproved masters) are skipped.
    status: Literal["new", "exists", "candidate"]
    variant_id: str | None = None
    # Set on a submit: the cell's job, or why it could not be submitted.
    job_id: str | None = None
    error: str | None = None


class SceneMatrixResponse(ApiModel):
    cells: list[SceneMatrixCellView]
    unit_credits: int
    # The new cells only — what a submit reserves in total.
    total_credits: int
    available_credits: int
    period_remaining: int | None = None
    within_spend_limit: bool
    sufficient: bool
    submitted: int = 0


# ---- 补齐缺失 (P2-4) -----------------------------------------------------------

FillSlot = Literal["portrait", "front", "side", "back", "expressions"]


class LookFillRequest(ApiModel):
    # Restrict to these slots; default every missing one.
    slots: list[FillSlot] | None = Field(default=None, max_length=5)
    # The expression image's faces (default: six everyday expressions).
    expressions: list[CharacterExpression] | None = Field(
        default=None, min_length=1, max_length=MAX_CHARACTER_EXPRESSIONS
    )
    quality_tier: QualityTier = QualityTier.STANDARD
    aspect_ratio: str = Field(default="16:9", max_length=16)
    # `true` (the default) only plans and prices; `false` submits the next
    # wave (one job).
    dry_run: bool = True


class LookFillLineView(ApiModel):
    wave: int
    slots: list[FillSlot]
    output_count: int
    credits: int


class LookFillResponse(ApiModel):
    # Each slot: `present` (approved), `candidate` (only candidates — approve
    # or delete them; never regenerated) or `missing`.
    gaps: dict[FillSlot, Literal["present", "candidate", "missing"]]
    lines: list[LookFillLineView]
    total_credits: int
    available_credits: int
    period_remaining: int | None = None
    within_spend_limit: bool
    sufficient: bool
    # Set on a submit: the job for the next wave and the slots it fills.
    submitted_job_id: str | None = None
    submitted_slots: list[FillSlot] = Field(default_factory=list)
