"""Generation, upload, credit and notification payloads."""

from __future__ import annotations

import datetime as dt
from typing import Any, Literal

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
from app.platform_config.schemas import MAX_GENERATION_DURATION_SECONDS

# Fixed voice roster for `audio_generation`, mirrored by the creative studio's
# voice picker and passed through verbatim to the AiHubMix `/v1/audio/speech`
# call. Not config-centre material: changing the provider's own voice ids
# means a code change either way, so a constant is honest about that.
AUDIO_VOICES: frozenset[str] = frozenset({"alloy", "echo", "fable", "onyx", "nova", "shimmer"})
H3_VIDEO_ASPECT_RATIOS: frozenset[str] = frozenset({"16:9", "9:16", "1:1", "4:3", "3:4", "21:9"})


class VideoGenerationOptions(ApiModel):
    """Typed H3 options; arbitrary provider JSON and webhooks are forbidden."""

    resolution: Literal["2K"] = "2K"
    reference_mode: Literal["input_references", "frame_images"] = "input_references"
    first_frame_asset_id: str | None = Field(default=None, max_length=40)
    last_frame_asset_id: str | None = Field(default=None, max_length=40)


class GenerationParams(ApiModel):
    prompt: str = Field(min_length=1, max_length=2000)
    negative_prompt: str | None = Field(default=None, max_length=1000)
    seed: int | None = Field(default=None, ge=0, le=2**31 - 1)
    aspect_ratio: str = Field(default="16:9", pattern=r"^\d{1,2}:\d{1,2}$")
    duration_seconds: int = Field(default=0, ge=0, le=MAX_GENERATION_DURATION_SECONDS)
    reference_asset_ids: list[str] = Field(default_factory=list, max_length=9)
    video_options: VideoGenerationOptions | None = None
    style_preset_id: str | None = None
    # Names a `shortform.profiles` entry. Absent for ordinary generation, which
    # is why every downstream check treats it as optional.
    shortform_profile: str | None = Field(default=None, max_length=64)
    # Cast picked from the character library. Their reference images and voice
    # descriptions are merged into `reference_asset_ids` / `extra` in
    # `characters.service.apply_character_refs` before the job is priced.
    character_ids: list[str] = Field(default_factory=list, max_length=4)
    # Which `CreationSkill` (if any) the client applied to this request. Not
    # trusted blindly: the `skill_context` workflow node re-fetches and
    # re-merges the skill's own params server-side before generation runs.
    skill_id: str | None = Field(default=None, max_length=40)
    extra: dict[str, Any] = Field(default_factory=dict)


class QuoteRequest(ApiModel):
    operation: Operation
    quality_tier: QualityTier
    duration_seconds: int = Field(default=0, ge=0, le=MAX_GENERATION_DURATION_SECONDS)


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
        options = self.params.video_options
        if self.operation not in video_ops and options is not None:
            raise ValueError("video_options 仅适用于视频生成。")
        if options is not None:
            if not 4 <= self.params.duration_seconds <= 15:
                raise ValueError("MiniMax H3 视频时长必须为 4-15 秒。")
            if self.params.aspect_ratio not in H3_VIDEO_ASPECT_RATIOS:
                raise ValueError(f"MiniMax H3 画幅必须为: {sorted(H3_VIDEO_ASPECT_RATIOS)}。")
            if options.reference_mode == "frame_images":
                if not options.first_frame_asset_id:
                    raise ValueError("首尾帧模式必须提供首帧图片。")
                if self.params.reference_asset_ids or self.params.character_ids:
                    raise ValueError("首尾帧与普通参考素材、角色参考图互斥。")
                if self.operation != Operation.IMAGE_TO_VIDEO:
                    raise ValueError("首尾帧模式必须使用 image_to_video 操作。")
            elif options.first_frame_asset_id or options.last_frame_asset_id:
                raise ValueError("普通参考素材模式不能传入首帧或尾帧。")
        has_frame_input = bool(options and options.first_frame_asset_id)
        if (
            self.operation == Operation.IMAGE_TO_VIDEO
            and not self.params.reference_asset_ids
            and not has_frame_input
        ):
            raise ValueError("图生视频必须提供参考图。")
        if self.operation == Operation.IMAGE_TO_IMAGE and not self.params.reference_asset_ids:
            raise ValueError("图生图必须提供参考图。")
        if self.operation == Operation.AUDIO_GENERATION:
            voice = self.params.extra.get("voice")
            if voice not in AUDIO_VOICES:
                raise ValueError(f"音频生成必须指定音色，可选: {sorted(AUDIO_VOICES)}。")
        return self


class JobInputQuestionOption(ApiModel):
    value: str
    label: str


class JobInputQuestionView(ApiModel):
    id: str
    kind: Literal["single_choice", "multi_choice", "free_text"]
    prompt: str
    options: list[JobInputQuestionOption] = Field(default_factory=list)
    required: bool = False


class JobInputRequestResponse(ApiModel):
    """What a planning/`copy_generate` node is waiting on, for the question form."""

    job_id: str
    node_id: str
    questions: list[JobInputQuestionView]
    expires_at: dt.datetime


class JobAnswerItem(ApiModel):
    question_id: str = Field(min_length=1, max_length=64)
    # `str` for `single_choice`/`free_text`, `list[str]` for `multi_choice` —
    # mirrors `ClarifyPanel`'s own answer shape on the frontend.
    value: str | list[str]


class JobAnswerRequest(ApiModel):
    answers: list[JobAnswerItem] = Field(default_factory=list, max_length=20)


class PromoteJobRequest(ApiModel):
    quality_tier: QualityTier
    # Client-side ceiling on the promoted job, same semantics as
    # `GenerationJobCreateRequest.max_credits`.
    max_credits: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _cannot_promote_to_preview(self) -> PromoteJobRequest:
        if self.quality_tier == QualityTier.PREVIEW:
            raise ValueError("升级档位不能仍为 preview。")
        return self


class RouteSummary(ApiModel):
    provider: str
    provider_kind: str
    model_or_workflow: str
    reason: str = ""


class RoutingCandidate(ApiModel):
    """One row of the router's decision trace, kept for replay in the console."""

    provider: str
    eligible: bool
    filter_reason: str | None = None
    success_rate: float = 0.0
    avg_latency_ms: int = 0
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
    output_media_type: MediaType | None = None
    draft_id: str | None = None
    failure_code: str | None = None
    failure_message: str | None = None
    cancel_requested: bool = False
    promoted_from_job_id: str | None = None
    created_at: dt.datetime
    finished_at: dt.datetime | None = None
    events: list[JobEventResponse] = Field(default_factory=list)


class UploadPresignRequest(ApiModel):
    filename: str = Field(min_length=1, max_length=255)
    mime_type: str = Field(min_length=3, max_length=128)
    size_bytes: int = Field(ge=1, le=512 * 1024 * 1024)
    checksum_sha256: str = Field(min_length=64, max_length=64, pattern=r"^[a-f0-9]{64}$")
    purpose: str = Field(
        pattern=(
            r"^(generation_reference|avatar|profile_cover|consent_evidence|learn_media"
            r"|style_gallery_cover)$"
        )
    )


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


class RedeemCodeRequest(ApiModel):
    code: str = Field(min_length=1, max_length=32)


class RedeemCodeResponse(ApiModel):
    credits_granted: int
    available_balance: int


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
