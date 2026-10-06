"""Script-writing (文案创作) request/response models."""

from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from pydantic import Field

from app.api.schemas.blocking import BlockingState
from app.api.schemas.common import ApiModel
from app.domain.blocking.vocabulary import BlockingAspectRatio
from app.domain.image_assets.vocabulary import AgeStage, SceneLighting, ScenePeriod
from app.models.enums import QualityTier


class ScriptBlock(ApiModel):
    type: str
    character: str | None = None
    text: str


class ScriptScene(ApiModel):
    heading: str
    blocks: list[ScriptBlock]
    # Links this scene heading to a reusable `Scene` asset (reference
    # stills/clips) via `PATCH /v1/scripts/{episode_id}/links` — the model
    # never sets this itself, only a user's own link action does; see
    # `app.agents.copywriter._sanitize_script`.
    ref_id: str | None = None
    # Which of that scene's variants (黄昏/战损…) this heading uses; unset =
    # its default. Same link rules as `ref_id`.
    variant_id: str | None = None


class ScriptCharacter(ApiModel):
    name: str
    traits: str = ""
    # Links this character to a reusable `Character` asset (reference
    # images/videos) — same rule as `ScriptScene.ref_id` above.
    character_ref_id: str | None = None
    # Which of that character's looks (婚礼/战甲…) this script uses; unset =
    # the default look.
    look_id: str | None = None


class ScriptProp(ApiModel):
    """A story object (信物、凶器…) the asset breakdown found in the script
    (`POST /v1/scripts/{id}:breakdown-apply`). The model never writes props
    itself; `copywriter._carry_over_links` keeps them across revision turns."""

    name: str
    description: str = ""
    # Links this prop to a reusable prop card — same rule as
    # `ScriptCharacter.character_ref_id`.
    prop_ref_id: str | None = None


class ScriptDocument(ApiModel):
    title: str = ""
    logline: str = ""
    characters: list[ScriptCharacter] = Field(default_factory=list)
    scenes: list[ScriptScene] = Field(default_factory=list)
    # ≤ `copywriter.MAX_PROPS`, trimmed by `_sanitize_script`.
    props: list[ScriptProp] = Field(default_factory=list)


class ScriptCreateRequest(ApiModel):
    title: str = Field(default="", max_length=60)
    idea: str = Field(min_length=1, max_length=20_000)
    referenced_skill_ids: list[str] = Field(default_factory=list, max_length=5)
    # When set, the new episode is attached to this existing `kind=drama`
    # series (the "新增一集" entry point from a series' own detail page)
    # instead of spinning up a brand-new series — see
    # `script_writing_service.prepare_new_script`.
    series_id: str | None = Field(default=None, max_length=40)


class ScriptRetryRequest(ApiModel):
    """Re-runs the first draft for an empty episode shell.

    `idea` is optional: omitting it (or sending a blank string) reuses
    `DramaEpisode.source_idea` persisted by `prepare_new_script`. Sending a
    new idea overwrites that stored prompt before the stream starts.
    """

    idea: str | None = Field(default=None, max_length=20_000)
    referenced_skill_ids: list[str] = Field(default_factory=list, max_length=5)


class ScriptTurnRequest(ApiModel):
    message: str = Field(min_length=1, max_length=2000)
    referenced_skill_ids: list[str] = Field(default_factory=list, max_length=5)
    # The exact document the composer is looking at right now — usually the
    # latest turn, but possibly an earlier one the user has browsed back to
    # (`ScriptEditor.selectTurn`). Omitting it falls back to the episode's
    # own persisted `script_json` (today's behavior); when present it lets a
    # revision apply on top of whatever is actually on screen instead of
    # silently jumping to the true latest turn underneath the user.
    current_script: ScriptDocument | None = None


class ScriptCharacterLinkUpdate(ApiModel):
    name: str
    character_ref_id: str | None = None
    # A look of `character_ref_id` (authoritative with it: `None` = default).
    look_id: str | None = Field(default=None, max_length=40)


class ScriptSceneLinkUpdate(ApiModel):
    heading: str
    ref_id: str | None = None
    # A variant of `ref_id` (authoritative with it: `None` = default).
    variant_id: str | None = Field(default=None, max_length=40)


class ScriptPropLinkUpdate(ApiModel):
    name: str = Field(min_length=1, max_length=60)
    prop_ref_id: str | None = None


class ScriptLinksUpdateRequest(ApiModel):
    """A structural edit, not a content revision — never goes through the
    LLM turn machinery (no `AgentRun`, no new `EpisodeScriptTurn`). Matched
    by `name`/`heading` against the episode's current `script_json` rather
    than by index, since either list can be reordered by a revision turn
    that runs concurrently with a link update landing.
    """

    characters: list[ScriptCharacterLinkUpdate] = Field(default_factory=list, max_length=20)
    scenes: list[ScriptSceneLinkUpdate] = Field(default_factory=list, max_length=40)
    # A name the script has no prop for yet is appended (with a link only).
    props: list[ScriptPropLinkUpdate] = Field(default_factory=list, max_length=40)


class ScriptContentUpdateRequest(ApiModel):
    """A direct hand-edit of the script text — bypasses the LLM turn
    machinery, same as `ScriptLinksUpdateRequest`. The full document, not a
    per-field patch, so `app.agents.copywriter._sanitize_script` can do all
    the bounds/shape validation the same way it does for every other write
    path into `script_json`.
    """

    script: ScriptDocument


class ScriptTurnSummary(ApiModel):
    id: str
    turn_no: int
    user_message: str
    summary: str
    referenced_skill_ids: list[str] = Field(default_factory=list)
    created_at: dt.datetime
    # The model's reasoning trace for this turn (empty for a turn written
    # before this field existed, or one whose model/endpoint never produced
    # one) — rendered as a collapsed-by-default "思考" disclosure under the
    # turn's summary bubble, never inside the right-side script view.
    thinking: str = ""
    # `script` for a 文案创作 chat turn, `blocking` for one sent from the 白膜
    # studio (which may have rewritten the script as well).
    origin: str = "script"


class ScriptSummaryResponse(ApiModel):
    episode_id: str
    title: str
    logline: str = ""
    status: str
    turn_count: int
    updated_at: dt.datetime


class ScriptDetailResponse(ApiModel):
    episode_id: str
    series_id: str
    title: str
    status: str
    script: ScriptDocument
    turns: list[ScriptTurnSummary]
    # The author's first-draft prompt, so the empty-shell page can retry
    # without asking them to re-type it. Empty when this episode predates
    # persistence *and* no nearby `script_draft` AgentRun could be recovered.
    source_idea: str = ""
    source_referenced_skill_ids: list[str] = Field(default_factory=list)
    # Latest failed-generation excerpt from the episode's script notification,
    # so a refresh still shows why the first draft did not land.
    last_error: str | None = None
    # The 白膜 blockout's head state; `None` while `blocking_studio_enabled`
    # is off for this user.
    blocking: BlockingState | None = None
    created_at: dt.datetime
    updated_at: dt.datetime


class ScriptTurnSnapshotResponse(ApiModel):
    turn_id: str
    turn_no: int
    summary: str
    script: ScriptDocument


class ScriptExtractResponse(ApiModel):
    filename: str
    text: str
    char_count: int
    truncated: bool


class BlockingTurnRequest(ApiModel):
    message: str = Field(min_length=1, max_length=2000)
    # Same meaning as `ScriptTurnRequest.current_script`.
    current_script: ScriptDocument | None = None


class BlockingPatchRequest(ApiModel):
    """A manual 白膜 edit — the browser's whole document, re-validated by
    `app.domain.blocking.sanitize.sanitize_blocking(mode="manual")`."""

    document: dict[str, Any]
    base_version_no: int = Field(ge=0)


class BlockingSettingsRequest(ApiModel):
    # `None` clears the target back to "derive from the script".
    target_duration_seconds: int | None = Field(default=None, ge=1, le=1800)
    aspect_ratio: BlockingAspectRatio | None = None
    base_version_no: int = Field(ge=0)


# ---- 剧本拆解建卡 (AC-9) -------------------------------------------------------

BreakdownKind = Literal["character", "scene", "prop"]
BreakdownAction = Literal["create", "link", "skip"]


class ScriptBreakdownMatch(ApiModel):
    """One of the caller's own cards with the proposal's name."""

    id: str
    name: str


class ScriptBreakdownItem(ApiModel):
    """One proposed card. `headings`: a scene's headings set at this place,
    or the headings a prop appears in; empty for a character. Presets are
    only set for the kind they belong to (`age_stage` character, `period` /
    `lighting` scene)."""

    kind: BreakdownKind
    name: str
    description: str = ""
    headings: list[str] = Field(default_factory=list)
    age_stage: AgeStage | None = None
    period: ScenePeriod | None = None
    lighting: SceneLighting | None = None
    # The caller's card this script already links (`character_ref_id`, the
    # first linked heading's `ref_id`, the prop's `prop_ref_id`).
    linked_card_id: str | None = None
    matches: list[ScriptBreakdownMatch] = Field(default_factory=list)


class ScriptBreakdownResponse(ApiModel):
    characters: list[ScriptBreakdownItem]
    scenes: list[ScriptBreakdownItem]
    props: list[ScriptBreakdownItem]
    # The model gave nothing usable: characters and places come straight
    # from the script, and no props were found.
    degraded: bool = False


class ScriptBreakdownApplyItem(ApiModel):
    kind: BreakdownKind
    # A character's name in the script, a scene card's name, a prop's name.
    name: str = Field(min_length=1, max_length=60)
    action: BreakdownAction
    # `link`: one of the caller's cards of `kind`.
    card_id: str | None = Field(default=None, max_length=40)
    # `create`: the new card's description.
    description: str = Field(default="", max_length=2000)
    # Scene: the headings linked to the card (required unless `skip`).
    headings: list[str] = Field(default_factory=list, max_length=40)
    age_stage: AgeStage | None = None
    period: ScenePeriod | None = None
    lighting: SceneLighting | None = None


class ScriptBreakdownGenerate(ApiModel):
    """First images for the cards this apply creates: a character's identity
    portrait, a scene's master plate, a prop's hero plate."""

    enabled: bool = False
    quality_tier: QualityTier = QualityTier.STANDARD


class ScriptBreakdownApplyRequest(ApiModel):
    items: list[ScriptBreakdownApplyItem] = Field(default_factory=list, max_length=100)
    generate: ScriptBreakdownGenerate = Field(default_factory=ScriptBreakdownGenerate)
    # Validates and prices without writing anything.
    dry_run: bool = True


class ScriptBreakdownApplyResult(ApiModel):
    kind: BreakdownKind
    name: str
    action: BreakdownAction
    card_id: str | None = None
    created: bool = False
    # The first-image job, when one was asked for and submitted.
    job_id: str | None = None
    credits: int = 0
    error: str | None = None


class ScriptBreakdownApplyResponse(ApiModel):
    items: list[ScriptBreakdownApplyResult]
    # The script after the links were written (unchanged on a dry run).
    script: ScriptDocument
    # Every first image priced through the same `quote_for` a submit uses.
    total_credits: int
    available_credits: int
    period_remaining: int | None = None
    within_spend_limit: bool
    sufficient: bool
    submitted: int = 0
    dry_run: bool
