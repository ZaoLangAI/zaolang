"""User-authored creation skill (shareable generation parameter template) payloads."""

from __future__ import annotations

import datetime as dt
from typing import Any

from pydantic import Field

from app.api.schemas.common import ApiModel
from app.api.schemas.works import AuthorSummary
from app.models.enums import CreationSkillCategory, CreationSkillStatus, CreationSkillVisibility


class CreationSkillSummary(ApiModel):
    """列表卡片投影，风格对齐 `learning.LearnPostSummary`。"""

    id: str
    title: str
    description: str
    category: CreationSkillCategory
    cover_url: str | None = None
    author: AuthorSummary
    visibility: CreationSkillVisibility
    status: CreationSkillStatus
    usage_count: int
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


class CreationSkillUpdateRequest(CreationSkillCreateRequest):
    pass
