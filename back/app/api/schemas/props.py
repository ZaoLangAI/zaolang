"""Prop library payloads (道具, AC-4) — mirrors `schemas/scenes.py`."""

from __future__ import annotations

import datetime as dt

from pydantic import Field

from app.api.schemas.asset_variants import AssetVariantView
from app.api.schemas.common import ApiModel, Timestamped
from app.domain.props.service import MAX_REFERENCE_ASSETS
from app.models.enums import CreationSkillStatus, CreationSkillVisibility


class PropCreateRequest(ApiModel):
    name: str = Field(min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=2000)
    reference_asset_ids: list[str] = Field(default_factory=list, max_length=MAX_REFERENCE_ASSETS)


class PropUpdateRequest(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=2000)
    reference_asset_ids: list[str] | None = Field(default=None, max_length=MAX_REFERENCE_ASSETS)


class PropReferenceAsset(ApiModel):
    asset_id: str
    view: str = "general"
    label: str | None = None
    url: str | None = None
    created_at: dt.datetime | None = None


class PropResponse(Timestamped):
    id: str
    name: str
    description: str | None = None
    # Flat projection of the variants' approved images (the hero plate first).
    reference_assets: list[PropReferenceAsset] = Field(default_factory=list)
    variants: list[AssetVariantView] = Field(default_factory=list)
    anchor_entry_id: str | None = None
    status: CreationSkillStatus = CreationSkillStatus.DRAFT
    visibility: CreationSkillVisibility = CreationSkillVisibility.PRIVATE
    access_credits: int = 0
