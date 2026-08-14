"""User-authored creation skill (shareable generation parameter template) payloads."""

from __future__ import annotations

import datetime as dt
from typing import Any

from pydantic import Field

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
    created_at: dt.datetime


class CreationSkillDetail(CreationSkillSummary):
    cover_asset_id: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    reject_reason: str | None = None


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
