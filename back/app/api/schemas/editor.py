"""Drama editor request/response models. Never expose external editor types."""

from __future__ import annotations

import datetime as dt
from typing import Any

from pydantic import Field

from app.api.schemas.common import ApiModel


class DramaSeriesCreateRequest(ApiModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    default_locale: str = "zh-CN"
    shortform_profile_key: str | None = None
    allow_external_models: bool = False


class DramaSeriesResponse(ApiModel):
    id: str
    title: str
    description: str | None = None
    kind: str
    default_locale: str
    status: str
    allow_external_models: bool
    shortform_profile_key: str | None = None
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
    created_at: dt.datetime


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
