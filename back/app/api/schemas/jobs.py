"""Generation, upload, credit and notification payloads."""

from __future__ import annotations

import datetime as dt
from typing import Any

from pydantic import Field, model_validator

from app.api.schemas.common import ApiModel
from app.models.enums import (
    JobStatus,
    LedgerEntryType,
    MediaType,
    NotificationType,
    Operation,
    QualityTier,
)


class GenerationParams(ApiModel):
    prompt: str = Field(min_length=1, max_length=2000)
    negative_prompt: str | None = Field(default=None, max_length=1000)
    seed: int | None = Field(default=None, ge=0, le=2**31 - 1)
    aspect_ratio: str = Field(default="16:9", pattern=r"^\d{1,2}:\d{1,2}$")
    duration_seconds: int = Field(default=0, ge=0, le=30)
    reference_asset_ids: list[str] = Field(default_factory=list, max_length=6)
    style_preset_id: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class QuoteRequest(ApiModel):
    operation: Operation
    quality_tier: QualityTier
    duration_seconds: int = Field(default=0, ge=0, le=30)


class QuoteResponse(ApiModel):
    credits: int
    estimated_seconds: int
    breakdown: dict[str, int]
    available_credits: int
    sufficient: bool


class GenerationJobCreateRequest(ApiModel):
    operation: Operation
    quality_tier: QualityTier
    params: GenerationParams
    draft_id: str | None = None
    source_work_id: str | None = None
    # Client-side ceiling. The job is refused rather than silently trimmed if
    # the quote exceeds it.
    max_credits: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _video_needs_duration(self) -> GenerationJobCreateRequest:
        video_ops = {Operation.TEXT_TO_VIDEO, Operation.IMAGE_TO_VIDEO, Operation.VIDEO_TO_VIDEO}
        if self.operation in video_ops and self.params.duration_seconds <= 0:
            raise ValueError("视频生成必须指定时长。")
        if self.operation == Operation.IMAGE_TO_VIDEO and not self.params.reference_asset_ids:
            raise ValueError("图生视频必须提供参考图。")
        return self


class RouteSummary(ApiModel):
    provider: str
    provider_kind: str
    model_or_workflow: str
    score: float = 0.0
    reason: str = ""


class RoutingCandidate(ApiModel):
    """One row of the router's decision trace, kept for replay in the console."""

    provider: str
    eligible: bool
    filter_reason: str | None = None
    quality_score: float = 0.0
    latency_score: float = 0.0
    cost_score: float = 0.0
    reliability_score: float = 0.0
    total_score: float = 0.0
    effective_cost: int = 0


class JobEventResponse(ApiModel):
    sequence: int
    event_type: str
    status: JobStatus
    progress: int
    message: str
    internal_code: str | None = None
    created_at: dt.datetime


class GenerationJobResponse(ApiModel):
    id: str
    status: JobStatus
    operation: Operation
    quality_tier: QualityTier
    progress: int = 0
    quoted_credits: int
    reserved_credits: int
    actual_credits: int | None = None
    estimated_seconds: int = 0
    route: RouteSummary | None = None
    output_asset_id: str | None = None
    output_url: str | None = None
    draft_id: str | None = None
    failure_code: str | None = None
    failure_message: str | None = None
    cancel_requested: bool = False
    created_at: dt.datetime
    finished_at: dt.datetime | None = None
    events: list[JobEventResponse] = Field(default_factory=list)


class UploadPresignRequest(ApiModel):
    filename: str = Field(min_length=1, max_length=255)
    mime_type: str = Field(min_length=3, max_length=128)
    size_bytes: int = Field(ge=1, le=512 * 1024 * 1024)
    checksum_sha256: str = Field(min_length=64, max_length=64, pattern=r"^[a-f0-9]{64}$")
    purpose: str = Field(pattern=r"^(generation_reference|avatar|profile_cover|consent_evidence)$")


class UploadPresignResponse(ApiModel):
    upload_session_id: str
    upload_url: str
    object_key: str
    expires_at: dt.datetime
    required_headers: dict[str, str] = Field(default_factory=dict)


class UploadCompleteRequest(ApiModel):
    upload_session_id: str


class AssetResponse(ApiModel):
    id: str
    media_type: MediaType
    mime_type: str
    size_bytes: int
    width: int | None = None
    height: int | None = None
    duration_ms: int | None = None
    url: str | None = None
    moderation_status: str
    is_prototype: bool = False
    ai_generated: bool = False


class ProvenanceResponse(ApiModel):
    """AI disclosure for a generated asset.

    `signed` is false until a real C2PA signer is configured; the claim is
    still worth showing, but it must not be presented as verified.
    """

    asset_id: str
    generation_job_id: str | None = None
    claim: dict[str, Any]
    signed: bool = False


class CreditBalanceResponse(ApiModel):
    available: int
    reserved: int
    currency: str = "CREDIT"


class LedgerEntryResponse(ApiModel):
    id: str
    type: LedgerEntryType
    amount: int
    balance_after: int
    job_id: str | None = None
    reason: str | None = None
    created_at: dt.datetime


class CreditPackageResponse(ApiModel):
    id: str
    slug: str
    credits: int
    bonus_credits: int
    price_minor: int
    currency: str
    region: str


class CheckoutRequest(ApiModel):
    package_id: str


class CheckoutResponse(ApiModel):
    payment_intent_id: str
    checkout_url: str
    external_reference: str
    amount_minor: int
    currency: str


class NotificationResponse(ApiModel):
    id: str
    type: NotificationType
    title_key: str
    payload: dict[str, Any] = Field(default_factory=dict)
    target_type: str | None = None
    target_id: str | None = None
    read: bool = False
    created_at: dt.datetime


class ReportCreateRequest(ApiModel):
    subject_type: str = Field(pattern=r"^(work|asset|user|comment)$")
    subject_id: str
    reason: str
    detail: str | None = Field(default=None, max_length=2000)
