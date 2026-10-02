"""Character looks / scene variants and their images (P1, see
`docs/asset-variants-p1.md`). Shared by `/v1/characters/{id}/looks…` and
`/v1/scenes/{id}/variants…`."""

from __future__ import annotations

import datetime as dt
from typing import Any

from pydantic import Field

from app.api.schemas.common import ApiModel
from app.domain.asset_variants.service import MAX_VARIANT_NAME_LEN
from app.domain.image_assets.vocabulary import (
    MAX_CHARACTER_EXPRESSIONS,
    CharacterExpression,
    SceneLighting,
    ScenePeriod,
    SceneState,
    SceneWeather,
)
from app.models.enums import AssetEntryStatus, AssetEntryType


class VariantPresets(ApiModel):
    """Scene variant presets (P0 vocabulary) or a look's `age_stage`."""

    lighting: SceneLighting | None = None
    weather: SceneWeather | None = None
    state: SceneState | None = None
    period: ScenePeriod | None = None
    age_stage: str | None = Field(default=None, max_length=20)


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
    is_default: bool
    sort_order: int
    entries: list[AssetEntryView] = Field(default_factory=list)


class AssetVariantCreateRequest(ApiModel):
    name: str = Field(min_length=1, max_length=MAX_VARIANT_NAME_LEN)
    description: str | None = Field(default=None, max_length=2000)
    presets: VariantPresets | None = None


class AssetVariantUpdateRequest(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=MAX_VARIANT_NAME_LEN)
    description: str | None = Field(default=None, max_length=2000)
    presets: VariantPresets | None = None
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
