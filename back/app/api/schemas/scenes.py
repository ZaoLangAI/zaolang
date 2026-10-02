"""Scene library payloads.

A scene is stored as a `CreationSkill` (`category=scene_asset`) — see
`app.domain.scenes.service.SceneView` — so `SceneResponse` also surfaces the
skill lifecycle fields (`status`/`visibility`/`access_credits`) a scene
library UI needs to show "draft / 审核中 / 已发布", mirroring
`app.api.schemas.characters.CharacterResponse`.
"""

from __future__ import annotations

import datetime as dt

from pydantic import Field

from app.api.schemas.asset_variants import AssetVariantView
from app.api.schemas.common import ApiModel, Timestamped
from app.domain.scenes.service import MAX_REFERENCE_ASSETS
from app.models.enums import CreationSkillStatus, CreationSkillVisibility


class SceneCreateRequest(ApiModel):
    # Stored as `CreationSkill.title` (`VARCHAR(80)`).
    name: str = Field(min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=2000)
    reference_asset_ids: list[str] = Field(default_factory=list, max_length=MAX_REFERENCE_ASSETS)


class SceneUpdateRequest(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=2000)
    reference_asset_ids: list[str] | None = Field(default=None, max_length=MAX_REFERENCE_ASSETS)


class SceneReferenceAssetUpdateRequest(ApiModel):
    view: str | None = Field(default=None, max_length=32)
    label: str | None = Field(default=None, max_length=60)


class SceneReferenceAsset(ApiModel):
    asset_id: str
    view: str = "general"
    label: str | None = None
    url: str | None = None
    created_at: dt.datetime | None = None


class SceneResponse(Timestamped):
    id: str
    name: str
    description: str | None = None
    reference_assets: list[SceneReferenceAsset] = Field(default_factory=list)
    # The card's looks/variants with their images (P1); `reference_assets`
    # above is their flat P0-shaped projection, kept for older clients.
    variants: list[AssetVariantView] = Field(default_factory=list)
    anchor_entry_id: str | None = None
    status: CreationSkillStatus = CreationSkillStatus.DRAFT
    visibility: CreationSkillVisibility = CreationSkillVisibility.PRIVATE
    access_credits: int = 0
