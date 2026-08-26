"""Short-video spec, compliance and distribution payloads."""

from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from pydantic import Field, model_validator

from app.api.schemas.common import ApiModel
from app.models.enums import (
    DistributionChannel,
    ImageAssetKind,
    Operation,
    PublicationStatus,
    QualityTier,
    VideoAssetKind,
)

# Mirrors `app.agents.copywriter.DIMENSION_KEYS` / `.ENHANCE_DIRECTIONS`. Spelled
# out here rather than imported so the published contract does not depend on an
# agent module at import time; `tests/unit/test_prompt_enhance.py` asserts the
# two stay identical.
PromptDimensionKey = Literal[
    "subject",
    "scene",
    "action",
    "camera",
    "lighting",
    "mood",
    "pacing",
    "composition",
    "style",
    "detail",
]
PromptEnhanceDirection = Literal[
    "more_specific",
    "more_concise",
    "stronger_camera",
    "stronger_lighting",
    "more_dramatic",
]


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
    enable_clarifying_questions: bool
    enable_preview_picker: bool
    preview_candidate_count: int


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
    """A polish request, plus whatever the studio already knows about the job.

    Everything past `prompt` is optional: the context only sharpens the
    advice (camera notes belong on a video, not a poster), and a caller that
    has not picked an aspect ratio yet must still be able to ask.
    """

    prompt: str = Field(min_length=1, max_length=600)
    operation: Operation | None = None
    aspect_ratio: str | None = Field(default=None, max_length=16)
    duration_seconds: int | None = Field(default=None, ge=0, le=600)
    quality_tier: QualityTier | None = None
    # The style preset / skills already applied, joined for the agent to read.
    style_hint: str = Field(default="", max_length=200)
    has_reference: bool = False
    # Set when the author is iterating on a suggestion instead of asking for
    # the first one. `instruction` wins over `direction` where they disagree.
    direction: PromptEnhanceDirection | None = None
    instruction: str = Field(default="", max_length=200)
    # Only meaningful for an image job — `character`/`scene`/`cover` routes
    # the polish to that kind's dedicated default agent (`general`/omitted
    # behaves like today, and audio callers never set this).
    asset_kind: ImageAssetKind | None = None
    # The video-side equivalent — `character_action`/
    # `transition_video`/`cover_video` routes the polish to that kind's
    # dedicated default agent the same way `asset_kind` does for images (see
    # `agent_skills.service.ASSET_KIND_BUCKETS`, which spans both). A caller
    # sets at most one of the two — `context_from` prefers this field when
    # both are somehow present, since `asset_kind` defaults to unset for a
    # video job the same way `GenerationParams.asset_kind` does.
    video_asset_kind: VideoAssetKind | None = None


class PromptDimensionView(ApiModel):
    """One diagnosed aspect of the description, rendered as a checklist row."""

    key: PromptDimensionKey
    status: Literal["missing", "weak", "ok"]
    hint: str


class PromptEnhanceResponse(ApiModel):
    prompt: str
    detail_level: Literal["sparse", "adequate", "detailed"]
    feedback: str
    dimensions: list[PromptDimensionView] = Field(default_factory=list)
    # The phrases this round actually added, so the panel can show what
    # changed without diffing two blocks of prose.
    additions: list[str] = Field(default_factory=list)


class PromptClarifyRequest(ApiModel):
    prompt: str = Field(min_length=1, max_length=600)


class ClarifyQuestionOption(ApiModel):
    value: str
    label: str


class ClarifyQuestionResponse(ApiModel):
    id: str
    kind: Literal["single_choice", "multi_choice", "free_text"]
    prompt: str
    options: list[ClarifyQuestionOption] = Field(default_factory=list)
    required: bool


class PromptClarifyResponse(ApiModel):
    needs_clarification: bool
    questions: list[ClarifyQuestionResponse] = Field(default_factory=list)
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
