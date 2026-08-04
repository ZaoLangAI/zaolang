"""Short-video spec, compliance and distribution payloads."""

from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from pydantic import Field, model_validator

from app.api.schemas.common import ApiModel
from app.models.enums import DistributionChannel, PublicationStatus


class ShortformProfileResponse(ApiModel):
    """One delivery spec, flattened so the client can validate locally.

    The same numbers drive the server-side checks, so a client that enforces
    them is only saving a round trip, never defining the rule.
    """

    key: str
    aspect_ratio: str
    width: int
    height: int
    min_duration_seconds: int
    max_duration_seconds: int
    max_title_length: int
    max_hashtags: int
    safe_area_top_pct: int
    safe_area_bottom_pct: int
    safe_area_right_pct: int
    require_ai_disclosure: bool


class ShortformProfilesResponse(ApiModel):
    default_profile: str
    profiles: list[ShortformProfileResponse]


class ComplianceCheckRequest(ApiModel):
    draft_id: str | None = None
    asset_id: str | None = None
    profile: str | None = Field(default=None, max_length=64)
    title: str = Field(default="", max_length=200)
    description: str = Field(default="", max_length=2000)
    hashtags: list[str] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def _needs_a_subject(self) -> ComplianceCheckRequest:
        if not self.draft_id and not self.asset_id:
            raise ValueError("请提供 draft_id 或 asset_id。")
        return self


class ComplianceCheckItem(ApiModel):
    code: str
    level: Literal["pass", "warn", "block"]
    message: str


class ComplianceCheckResponse(ApiModel):
    profile: ShortformProfileResponse
    checks: list[ComplianceCheckItem]
    # False when at least one check is a block; the publish action stays
    # disabled until it is not.
    passed: bool


class PromptEnhanceRequest(ApiModel):
    prompt: str = Field(min_length=1, max_length=600)


class PromptEnhanceResponse(ApiModel):
    prompt: str
    degraded: bool


class PublicationCreateRequest(ApiModel):
    channel: DistributionChannel = DistributionChannel.MANUAL_DOWNLOAD
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    hashtags: list[str] = Field(default_factory=list, max_length=30)
    cover_asset_id: str | None = None
    scheduled_at: dt.datetime | None = None


class PublicationIntentResponse(ApiModel):
    id: str
    work_id: str
    channel: DistributionChannel
    status: PublicationStatus
    payload: dict[str, Any] = Field(default_factory=dict)
    # Freshly signed on every read; the stored intent never holds a URL that
    # would already be expired when the history is opened.
    download_url: str | None = None
    external_post_id: str | None = None
    submitted_at: dt.datetime | None = None
    created_at: dt.datetime
