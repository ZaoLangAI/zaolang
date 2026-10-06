"""User-authored creation skill (shareable generation parameter template) payloads."""

from __future__ import annotations

import datetime as dt
from typing import Any

from pydantic import Field

from app.api.schemas.asset_variants import AssetVariantView
from app.api.schemas.character_voices import CharacterVoiceView
from app.api.schemas.common import ApiModel
from app.api.schemas.works import AuthorSummary
from app.models.enums import (
    CreationSkillCategory,
    CreationSkillStatus,
    CreationSkillVisibility,
    MediaType,
    Operation,
)


class CreationSkillSummary(ApiModel):
    """列表卡片投影，风格对齐 `learning.LearnPostSummary`。"""

    id: str
    title: str
    description: str
    category: CreationSkillCategory
    cover_url: str | None = None
    # Lets the client pick `<video>` vs `<img>` for the cover — a skill built
    # around a short-video effect can have a genuinely video preview instead
    # of a static frame, matching what the skill actually does.
    cover_media_type: MediaType | None = None
    # Operations this skill's template is meant for; empty means "any
    # operation" (same convention as `AgentProfile.operations_json`). Lets a
    # picker filter out, say, a video-only skill while composing an image.
    applicable_operations: list[Operation] = Field(default_factory=list)
    author: AuthorSummary
    visibility: CreationSkillVisibility
    status: CreationSkillStatus
    usage_count: int
    access_credits: int = 0
    viewer_unlocked: bool = True
    # This skill is a creation workflow: its `params_json` declares a variable
    # form to fill in before it runs. Computed, not stored. On the summary
    # rather than only on the detail because the list endpoints do not return
    # `params` at all, so a client filtering for workflows would otherwise have
    # to fetch every skill one at a time to find out.
    has_variables: bool = False
    created_at: dt.datetime


class CreationSkillDetail(CreationSkillSummary):
    cover_asset_id: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    reject_reason: str | None = None
    # Character/scene cards, once unlocked: their looks/variants with signed
    # images (the raw `reference_assets` id list is no longer in `params`).
    asset_variants: list[AssetVariantView] = Field(default_factory=list)
    anchor_asset_id: str | None = None
    # A character card's voices, once unlocked (no clone sample; jobs name
    # them by `voice_profile_id`).
    voices: list[CharacterVoiceView] = Field(default_factory=list)


class CreationSkillCreateRequest(ApiModel):
    title: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=300)
    category: CreationSkillCategory = CreationSkillCategory.OTHER
    params: dict[str, Any] = Field(default_factory=dict)
    cover_asset_id: str | None = None
    applicable_operations: list[Operation] = Field(default_factory=list)
    access_credits: int = Field(default=0, ge=0)


class CreationSkillUpdateRequest(CreationSkillCreateRequest):
    pass


class CreationSkillPricingRequest(ApiModel):
    access_credits: int = Field(ge=0)
