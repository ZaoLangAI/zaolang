"""Short-video delivery spec and prompt-polish payloads."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from app.api.schemas.common import ApiModel
from app.domain.image_assets.vocabulary import (
    MAX_CHARACTER_EXPRESSIONS,
    CharacterExpression,
    SceneLighting,
    ScenePeriod,
    SceneState,
    SceneWeather,
)
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


class ScriptSegmentBlock(ApiModel):
    """One colour-coded script block inside a clip-studio polish request.

    `breakpoint` is rejected — adding a cut here would shift `{heading}#{ordinal}`.
    """

    type: Literal["scene", "action", "camera", "dialogue"]
    character: str | None = Field(default=None, max_length=60)
    text: str = Field(default="", max_length=400)


class ScriptSegment(ApiModel):
    """The shootable blocks of one suggested cut, plus its scene heading."""

    heading: str = Field(default="", max_length=80)
    blocks: list[ScriptSegmentBlock] = Field(default_factory=list, max_length=60)


class PromptEnhanceRequest(ApiModel):
    """A polish request, plus whatever the studio already knows about the job.

    Everything past `prompt` is optional: the context only sharpens the
    advice (camera notes belong on a video, not a poster), and a caller that
    has not picked an aspect ratio yet must still be able to ask.
    """

    prompt: str = Field(min_length=1, max_length=4096)
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
    # Script clip studio only: polish the user prompt *and* this segment's
    # colour blocks in place. Omitted on the generic image/video studios.
    script_segment: ScriptSegment | None = None
    # Answers to the previous round's `questions`, keyed by question id. A
    # single_choice/free_text answer is a string, multi_choice a list. Sent
    # on the round *after* the coach asked; empty on the first pass.
    question_answers: dict[str, str | list[str]] = Field(default_factory=dict, max_length=8)
    # The image studio's expression / scene-preset picks (same vocabulary as
    # `GenerationParams`), so the coach polishes around them.
    character_expressions: list[CharacterExpression] | None = Field(
        default=None, max_length=MAX_CHARACTER_EXPRESSIONS
    )
    scene_lighting: SceneLighting | None = None
    scene_weather: SceneWeather | None = None
    scene_state: SceneState | None = None
    scene_period: ScenePeriod | None = None


class PromptDimensionView(ApiModel):
    """One diagnosed aspect of the description, rendered as a checklist row."""

    key: PromptDimensionKey
    status: Literal["missing", "weak", "ok"]
    hint: str


class PromptQuestionOptionView(ApiModel):
    value: str
    label: str


class PromptQuestionView(ApiModel):
    """A follow-up the coach wants answered before it polishes again.

    Mirrors `JobInputQuestionView` — the studio renders both through the same
    `QuestionField` control.
    """

    id: str
    kind: Literal["single_choice", "multi_choice", "free_text"]
    prompt: str
    options: list[PromptQuestionOptionView] = Field(default_factory=list)
    required: bool = False


class AppliedFormatSkillView(ApiModel):
    """A `format` skill the coach auto-attached this round — see
    `app.domain.skill_library.service.apply_matching_format_skills`."""

    id: str
    title: str


class ReferencedSkillView(ApiModel):
    """A `drama` skill matched to this story and shown to the coach as
    reference material — see `app.agents.skill_matcher`."""

    id: str
    title: str


class PromptEnhanceResponse(ApiModel):
    prompt: str
    detail_level: Literal["sparse", "adequate", "detailed"]
    feedback: str
    dimensions: list[PromptDimensionView] = Field(default_factory=list)
    # The phrases this round actually added, so the panel can show what
    # changed without diffing two blocks of prose.
    additions: list[str] = Field(default_factory=list)
    # `format`-category skills auto-attached because a diagnosed dimension
    # came back missing/weak — video operations only, always empty for an
    # image polish. Distinct from `additions`: these are library rows the
    # author could otherwise have picked by hand, not model-authored phrases.
    applied_format_skills: list[AppliedFormatSkillView] = Field(default_factory=list)
    # `drama`-category skills the matcher found for this story and showed the
    # coach. Unlike `applied_format_skills`, nothing here was appended to
    # `prompt` — the coach read them and chose what to use, so the panel
    # labels them as references rather than as additions.
    referenced_skills: list[ReferencedSkillView] = Field(default_factory=list)
    # Scene plates only today: what the coach still needs from the author
    # before the description is safe to generate from. Empty for every other
    # asset kind, and empty once the author has answered.
    questions: list[PromptQuestionView] = Field(default_factory=list)
    script_segment: ScriptSegment | None = None
