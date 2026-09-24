"""Drama editor request/response models. Never expose external editor types."""

from __future__ import annotations

import datetime as dt
from typing import Any

from pydantic import Field

from app.api.schemas.common import ApiModel
from app.api.schemas.works import AuthorSummary


class DramaSeriesCreateRequest(ApiModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    default_locale: str = "zh-CN"
    shortform_profile_key: str | None = None
    allow_external_models: bool = False
    english_title: str | None = Field(default=None, max_length=200)
    planned_episode_count: int | None = Field(default=None, ge=1, le=100_000)
    genre_tags: list[str] = Field(default_factory=list, max_length=20)
    target_platforms: list[str] = Field(min_length=1, max_length=10)
    logo_asset_id: str | None = Field(default=None, max_length=40)


class DramaSeriesUpdateRequest(ApiModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    english_title: str | None = Field(default=None, max_length=200)
    planned_episode_count: int | None = Field(default=None, ge=1, le=100_000)
    genre_tags: list[str] | None = Field(default=None, max_length=20)
    target_platforms: list[str] | None = Field(default=None, min_length=1, max_length=10)
    logo_asset_id: str | None = None


class DramaSeriesResponse(ApiModel):
    id: str
    title: str
    description: str | None = None
    kind: str
    default_locale: str
    status: str
    allow_external_models: bool
    shortform_profile_key: str | None = None
    english_title: str | None = None
    planned_episode_count: int | None = None
    genre_tags: list[str] = Field(default_factory=list)
    target_platforms: list[str] = Field(default_factory=list)
    logo_asset_id: str | None = None
    logo_url: str | None = None
    episode_count: int = 0
    script_count: int = 0
    video_count: int = 0
    published_count: int = 0
    created_at: dt.datetime
    updated_at: dt.datetime
    owner: AuthorSummary
    # "owner" for the series' own creator, "collaborator" for an active
    # co-creator viewing it — drives the frontend's 共创 badge/permission
    # branching (trash/publish/platform-connect stay owner-only regardless
    # of `is_collaboration`). See `zaolang-editor-drama`.
    viewer_role: str = "owner"
    # True once the series has at least one *active* collaborator — shown
    # even to the owner, so they can tell at a glance which of their own
    # series are shared.
    is_collaboration: bool = False
    collaborator_count: int = 0


class CollaboratorInviteRequest(ApiModel):
    # Either the target's `Profile.handle` or their registered `User.email` —
    # `collaborators._find_profile_by_identifier` tells them apart by
    # whether "@" appears anywhere but the first character.
    identifier: str = Field(min_length=1, max_length=320)


class CollaboratorResponse(ApiModel):
    id: str
    user_id: str
    handle: str
    display_name: str
    avatar_url: str | None = None
    status: str
    invited_by_user_id: str
    created_at: dt.datetime
    responded_at: dt.datetime | None = None


class CollaborationInviteResponse(ApiModel):
    """One pending invite in the current user's own inbox — enough to
    render `CollaborationInvitesDialog` without a follow-up request per
    invite."""

    id: str
    series_id: str
    series_title: str
    series_logo_url: str | None = None
    inviter: AuthorSummary
    created_at: dt.datetime


class DramaEpisodeCreateRequest(ApiModel):
    title: str = Field(min_length=1, max_length=200)
    episode_number: int | None = Field(default=None, ge=1, le=10_000)
    season_number: int = Field(default=1, ge=1, le=1_000)
    episode_kind: str = "main"
    synopsis: str | None = Field(default=None, max_length=4000)


class DramaEpisodeUpdateRequest(ApiModel):
    title: str | None = Field(default=None, max_length=200)
    synopsis: str | None = Field(default=None, max_length=4000)
    episode_kind: str | None = None
    season_number: int | None = Field(default=None, ge=1, le=1_000)
    episode_number: int | None = Field(default=None, ge=1, le=10_000)
    status: str | None = None
    # Present in `model_fields_set` means apply: a non-empty id binds the
    # roster thumbnail, `null` / "" clears it so auto-extract can refill.
    preview_asset_id: str | None = Field(default=None, max_length=40)


class DramaEpisodeResponse(ApiModel):
    id: str
    series_id: str
    season_number: int
    episode_number: int
    episode_kind: str
    title: str
    synopsis: str | None = None
    status: str
    canonical_work_id: str | None = None
    # Whether this episode has at least one `EpisodeScriptTurn` — lets the
    # series dashboard flag a script-writing shell whose first draft never
    # finished (see `script_writing_service.list_scripts`'s own relaxed
    # filter) without a second round trip to `GET /v1/scripts/{episode_id}`.
    has_script_turns: bool = False
    preview_asset_id: str | None = None
    preview_url: str | None = None
    # True when a video exists that `POST .../preview:from-video` can
    # extract from — batched on list so the roster does not N+1.
    has_preview_source: bool = False


class EpisodeContentLinkCreateRequest(ApiModel):
    content_type: str
    content_ref_id: str = Field(min_length=1, max_length=40)
    role: str = "candidate"


class EpisodeContentLinkResponse(ApiModel):
    id: str
    episode_id: str
    content_type: str
    content_ref_id: str
    role: str
    created_at: dt.datetime


class EpisodeSetCanonicalWorkRequest(ApiModel):
    work_id: str | None = None


class CutCreateRequest(ApiModel):
    asset_id: str
    job_id: str | None = None
    name: str = Field(default="主剪辑", min_length=1, max_length=120)
    kind: str = "full"


class CutFromJobRequest(ApiModel):
    job_id: str
    series_id: str | None = None
    title: str | None = Field(default=None, max_length=200)


class TimelineSummaryResponse(ApiModel):
    schema_version: int
    canvas: dict[str, Any]
    duration_ticks: int
    tracks: list[dict[str, Any]]
    brand_overlay: dict[str, Any] | None = None
    markers: list[dict[str, Any]] = Field(default_factory=list)


class RevisionAssetMeta(ApiModel):
    """Intrinsic facts about one asset a revision references — what the
    timeline needs to clamp a trim to the source's real length, label a
    clip, and size thumbnails — separate from the short-lived signed URL in
    `asset_urls` because these never expire."""

    media_type: str
    mime_type: str
    duration_ticks: int | None = None
    width: int | None = None
    height: int | None = None


class CutRevisionResponse(ApiModel):
    id: str
    cut_id: str
    revision_no: int
    parent_revision_id: str | None = None
    duration_ticks: int
    content_hash: str
    summary: TimelineSummaryResponse
    document: dict[str, Any] = Field(default_factory=dict)
    asset_urls: dict[str, str] = Field(default_factory=dict)
    asset_meta: dict[str, RevisionAssetMeta] = Field(default_factory=dict)
    created_at: dt.datetime


class CutUpdateRequest(ApiModel):
    name: str = Field(min_length=1, max_length=120)


class EpisodeCutResponse(ApiModel):
    id: str
    episode_id: str
    kind: str
    name: str
    status: str
    head_revision_id: str | None = None
    source_asset_id: str | None = None
    source_job_id: str | None = None
    source_url: str | None = None
    lease_held: bool = False
    head: CutRevisionResponse | None = None


class CutRevisionSummaryResponse(ApiModel):
    """Lightweight revision listing for the editor's history panel — no
    `document`/`asset_urls`, since browsing history shouldn't pull the full
    timeline document for every past version."""

    id: str
    cut_id: str
    revision_no: int
    parent_revision_id: str | None = None
    duration_ticks: int
    is_head: bool = False
    created_at: dt.datetime


class RevisionRestoreRequest(ApiModel):
    revision_id: str
    expected_revision_id: str | None = None
    lease_id: str
    lease_token: str


class LeaseAcquireRequest(ApiModel):
    browser_instance_id: str = Field(min_length=4, max_length=80)


class LeaseResponse(ApiModel):
    id: str
    cut_id: str
    expires_at: dt.datetime
    token: str | None = None
    base_revision_id: str | None = None


class ApplyCommandsRequest(ApiModel):
    schema_version: int = 1
    batch_id: str
    expected_revision_id: str | None = None
    commands: list[dict[str, Any]]
    lease_id: str
    lease_token: str


class EditPlanCreateRequest(ApiModel):
    goal: str = Field(min_length=1, max_length=2000)
    max_commands: int = Field(default=40, ge=1, le=100)
    profile_key: str | None = None


class EditPlanResponse(ApiModel):
    id: str
    cut_id: str
    base_revision_id: str
    status: str
    summary: str | None = None
    commands: list[dict[str, Any]]
    diff: dict[str, Any]
    warnings: list[Any]
    applied_revision_id: str | None = None
    expires_at: dt.datetime | None = None


class EditPlanApplyRequest(ApiModel):
    lease_id: str
    lease_token: str
    selected_indexes: list[int] | None = None


class VariantBatchCreateRequest(ApiModel):
    profile_keys: list[str] = Field(min_length=1, max_length=20)
    caption_language: str | None = None
    caption_mode: str = "burned"
    format: str = "mp4"


class DeliveryVariantResponse(ApiModel):
    id: str
    cut_revision_id: str
    profile_key: str
    width: int
    height: int
    format: str
    spec_hash: str
    status: str


class ExportQueueRequest(ApiModel):
    variant_ids: list[str] = Field(min_length=1, max_length=20)
    operation_key: str | None = None


class ExportClaimRequest(ApiModel):
    runner_instance_id: str = Field(min_length=4, max_length=80)
    chrome_or_edge: bool = False
    webcodecs: bool = False
    webgpu: bool = False


class ExportHeartbeatRequest(ApiModel):
    progress: int = Field(ge=0, le=100)
    stage: str = "encoding"


class ExportCompleteRequest(ApiModel):
    upload_session_id: str


class ExportFailRequest(ApiModel):
    code: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1, max_length=500)


class ExportUploadRequest(ApiModel):
    filename: str
    mime_type: str
    size_bytes: int = Field(gt=0)
    checksum_sha256: str = Field(min_length=64, max_length=64)


class EditorExportResponse(ApiModel):
    id: str
    variant_id: str
    status: str
    operation_key: str
    attempt: int
    progress: int
    output_asset_id: str | None = None
    failure_code: str | None = None
    failure_message: str | None = None


class EpisodeExportResponse(ApiModel):
    """One editor export made from an episode's own cut, joined with
    whatever publishing state it has reached — never bound to a draft
    (download-only), bound but not yet published, or bound and published
    (eligible to become the episode's final cut)."""

    id: str
    status: str
    profile_key: str
    width: int
    height: int
    format: str
    output_asset_id: str | None = None
    output_url: str | None = None
    created_at: dt.datetime
    bound_draft_id: str | None = None
    published_work_id: str | None = None
    is_canonical: bool = False


class EditorOperationResponse(ApiModel):
    id: str
    kind: str
    status: str
    progress: int
    result: dict[str, Any] = Field(default_factory=dict)
    error: dict[str, Any] | None = None


class EditorOperationEventResponse(ApiModel):
    sequence: int
    event_type: str
    status: str
    progress: int
    message: str


class BindEditorExportRequest(ApiModel):
    export_id: str
    confirmed: bool = False


class EnsureBoundDraftRequest(ApiModel):
    confirmed: bool = False
    draft_id: str | None = None


class McpTokenCreateRequest(ApiModel):
    series_id: str
    client_id: str = Field(min_length=1, max_length=80)
    scopes: list[str] = Field(min_length=1, max_length=8)


class McpTokenResponse(ApiModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: dt.datetime
    grant_id: str
    scopes: list[str]
    project_id: str
