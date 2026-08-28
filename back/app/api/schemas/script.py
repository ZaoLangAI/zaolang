"""Script-writing (文案创作) request/response models."""

from __future__ import annotations

import datetime as dt

from pydantic import Field

from app.api.schemas.common import ApiModel


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


class ScriptCharacter(ApiModel):
    name: str
    traits: str = ""
    # Links this character to a reusable `Character` asset (reference
    # images/videos) — same rule as `ScriptScene.ref_id` above.
    character_ref_id: str | None = None


class ScriptDocument(ApiModel):
    title: str = ""
    logline: str = ""
    characters: list[ScriptCharacter] = Field(default_factory=list)
    scenes: list[ScriptScene] = Field(default_factory=list)


class ScriptCreateRequest(ApiModel):
    title: str = Field(default="", max_length=60)
    idea: str = Field(min_length=1, max_length=2000)
    referenced_skill_ids: list[str] = Field(default_factory=list, max_length=5)
    # When set, the new episode is attached to this existing `kind=drama`
    # series (the "新增一集" entry point from a series' own detail page)
    # instead of spinning up a brand-new series — see
    # `script_writing_service.prepare_new_script`.
    series_id: str | None = Field(default=None, max_length=40)


class ScriptRetryRequest(ApiModel):
    """Re-describes the idea for `POST /v1/scripts/{episode_id}/retry` —
    the original text was never persisted anywhere on the episode shell
    (see `script_writing_service.retry_new_script`), so there is nothing to
    default this to; the caller (the empty-shell page) must ask again."""

    idea: str = Field(min_length=1, max_length=2000)
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


class ScriptSceneLinkUpdate(ApiModel):
    heading: str
    ref_id: str | None = None


class ScriptLinksUpdateRequest(ApiModel):
    """A structural edit, not a content revision — never goes through the
    LLM turn machinery (no `AgentRun`, no new `EpisodeScriptTurn`). Matched
    by `name`/`heading` against the episode's current `script_json` rather
    than by index, since either list can be reordered by a revision turn
    that runs concurrently with a link update landing.
    """

    characters: list[ScriptCharacterLinkUpdate] = Field(default_factory=list, max_length=20)
    scenes: list[ScriptSceneLinkUpdate] = Field(default_factory=list, max_length=40)


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
    created_at: dt.datetime
    updated_at: dt.datetime


class ScriptTurnSnapshotResponse(ApiModel):
    turn_id: str
    turn_no: int
    summary: str
    script: ScriptDocument
