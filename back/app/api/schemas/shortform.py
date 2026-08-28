"""Short-video delivery spec and prompt-polish payloads."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from app.api.schemas.common import ApiModel
from app.models.enums import ImageAssetKind, Operation, QualityTier, VideoAssetKind

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
