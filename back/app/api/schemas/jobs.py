"""Generation, upload, credit and notification payloads."""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from pydantic import Field, ValidationError, model_validator

from app.api.schemas.common import ApiModel
from app.models.enums import (
    CHARACTER_JOB_VIEWS,
    CharacterViewAngle,
    ImageAssetKind,
    JobStatus,
    LedgerEntryType,
    MediaType,
    NotificationType,
    Operation,
    QualityTier,
    VideoAssetKind,
)
from app.platform_config.schemas import MAX_GENERATION_DURATION_SECONDS

IMAGE_OPERATIONS: frozenset[Operation] = frozenset(
    {Operation.TEXT_TO_IMAGE, Operation.IMAGE_TO_IMAGE}
)

# Fixed voice roster for `audio_generation`, mirrored by the creative studio's
# voice picker and passed through verbatim to the AiHubMix `/v1/audio/speech`
# call. Not config-centre material: changing the provider's own voice ids
# means a code change either way, so a constant is honest about that.
AUDIO_VOICES: frozenset[str] = frozenset({"alloy", "echo", "fable", "onyx", "nova", "shimmer"})
VIDEO_OPERATIONS: frozenset[Operation] = frozenset(
    {Operation.TEXT_TO_VIDEO, Operation.IMAGE_TO_VIDEO, Operation.VIDEO_TO_VIDEO}
)
# Mirrored from `app.providers.aihubmix_media` so the C-end schema does not
# import a provider module. Keep the two in step.
H3_MIN_DURATION_SECONDS = 4
H3_MAX_DURATION_SECONDS = 15
H3_VIDEO_ASPECT_RATIOS: frozenset[str] = frozenset({"16:9", "9:16", "1:1", "4:3", "3:4", "21:9"})
# Same default the C-end studio ships (`generation-studio.tsx`); a prompt-only
# sandbox try-it must land inside the H3 4–15 window or route_score filters
# every video provider as `duration_below_provider_minimum`.
DEFAULT_SANDBOX_VIDEO_DURATION_SECONDS = 8


class VideoGenerationOptions(ApiModel):
    """Typed H3 options; arbitrary provider JSON and webhooks are forbidden."""

    resolution: Literal["2K"] = "2K"
    reference_mode: Literal["input_references", "frame_images"] = "input_references"
    first_frame_asset_id: str | None = Field(default=None, max_length=40)
    last_frame_asset_id: str | None = Field(default=None, max_length=40)


def apply_sandbox_generation_defaults(
    operation: Operation, params: dict[str, Any]
) -> dict[str, Any]:
    """Fills a video duration so a prompt-only sandbox try-it is routable.

    C-end submit already requires `duration_seconds > 0`. The sandbox dialog
    historically did not, so MiniMax H3 hard-filtered the only catalog entry
    as `duration_below_provider_minimum` and the job failed with "暂时没有
    可用的生成路线". Explicit zero / omitted duration becomes 8 seconds —
    the same default the C-end studio uses, inside the H3 4–15 window.
    """
    if operation not in VIDEO_OPERATIONS:
        return params
    raw = params.get("duration_seconds")
    if raw is None or raw == "" or raw == 0:
        return {**params, "duration_seconds": DEFAULT_SANDBOX_VIDEO_DURATION_SECONDS}
    return params


def validate_generation_params(
    operation: Operation,
    *,
    duration_seconds: int = 0,
    aspect_ratio: str = "16:9",
    reference_asset_ids: Sequence[str] | None = None,
    character_ids: Sequence[str] | None = None,
    scene_ids: Sequence[str] | None = None,
    video_options: VideoGenerationOptions | None = None,
    asset_kind: ImageAssetKind | None = None,
    video_asset_kind: VideoAssetKind | None = None,
    extra: Mapping[str, Any] | None = None,
) -> None:
    """Shared C-end / sandbox rules. Raises `ValueError` on illegal combinations."""
    references = list(reference_asset_ids or [])
    characters = list(character_ids or [])
    scenes = list(scene_ids or [])
    extras = extra or {}
    if (
        asset_kind is not None
        and asset_kind != ImageAssetKind.GENERAL
        and operation not in IMAGE_OPERATIONS
    ):
        raise ValueError("asset_kind 仅适用于文生图/图生图。")
    if (
        video_asset_kind is not None
        and video_asset_kind != VideoAssetKind.GENERAL
        and operation not in VIDEO_OPERATIONS
    ):
        raise ValueError("video_asset_kind 仅适用于视频生成。")
    if operation in VIDEO_OPERATIONS and duration_seconds <= 0:
        raise ValueError("视频生成必须指定时长。")
    if operation not in VIDEO_OPERATIONS and video_options is not None:
        raise ValueError("video_options 仅适用于视频生成。")
    if video_options is not None:
        if not H3_MIN_DURATION_SECONDS <= duration_seconds <= H3_MAX_DURATION_SECONDS:
            raise ValueError("MiniMax H3 视频时长必须为 4-15 秒。")
        if aspect_ratio not in H3_VIDEO_ASPECT_RATIOS:
            raise ValueError(f"MiniMax H3 画幅必须为: {sorted(H3_VIDEO_ASPECT_RATIOS)}。")
        if video_options.reference_mode == "frame_images":
            if not video_options.first_frame_asset_id:
                raise ValueError("首尾帧模式必须提供首帧图片。")
            if references or characters or scenes:
                raise ValueError("首尾帧与普通参考素材、角色参考图、场景参考图互斥。")
            if operation != Operation.IMAGE_TO_VIDEO:
                raise ValueError("首尾帧模式必须使用 image_to_video 操作。")
        elif video_options.first_frame_asset_id or video_options.last_frame_asset_id:
            raise ValueError("普通参考素材模式不能传入首帧或尾帧。")
    has_frame_input = bool(video_options and video_options.first_frame_asset_id)
    if operation == Operation.IMAGE_TO_VIDEO and not references and not has_frame_input:
        raise ValueError("图生视频必须提供参考图。")
    # `image_to_image` does NOT require a reference — the prompt is what's
    # mandatory; an attached image is optional extra context that rides
    # along with it (see `workflow_templates_service.canonical_operation`).
    # Whether the client calls this `text_to_image` or `image_to_image` is a
    # runtime detail, not a different validation regime.
    if operation == Operation.AUDIO_GENERATION:
        voice = extras.get("voice")
        if voice not in AUDIO_VOICES:
            raise ValueError(f"音频生成必须指定音色，可选: {sorted(AUDIO_VOICES)}。")


def prepare_sandbox_generation_params(
    operation: Operation, params: dict[str, Any]
) -> dict[str, Any]:
    """Applies sandbox defaults then the shared generation-param rules.

    Raises `ValueError` with a user-facing message; the sandbox route turns
    that into `ValidationFailed` so a bad duration never reaches Celery.
    Extra keys on the free-form sandbox `params` dict are left untouched —
    they must not be forced through `GenerationParams` (`extra=forbid`).
    """
    prepared = apply_sandbox_generation_defaults(operation, params)
    if operation not in VIDEO_OPERATIONS:
        return prepared
    options_raw = prepared.get("video_options")
    try:
        options = (
            None if options_raw is None else VideoGenerationOptions.model_validate(options_raw)
        )
        duration = int(prepared.get("duration_seconds") or 0)
    except (TypeError, ValueError) as exc:
        if isinstance(exc, ValidationError):
            first = exc.errors()[0]
            message = str(first.get("msg") or exc).removeprefix("Value error, ")
            raise ValueError(message) from exc
        raise ValueError("视频时长必须是整数秒。") from exc
    validate_generation_params(
        operation,
        duration_seconds=duration,
        aspect_ratio=str(prepared.get("aspect_ratio") or "16:9"),
        reference_asset_ids=list(prepared.get("reference_asset_ids") or []),
        character_ids=list(prepared.get("character_ids") or []),
        scene_ids=list(prepared.get("scene_ids") or []),
        video_options=options,
        asset_kind=_parsed_asset_kind(prepared.get("asset_kind")),
        video_asset_kind=_parsed_video_asset_kind(prepared.get("video_asset_kind")),
        extra=prepared.get("extra") if isinstance(prepared.get("extra"), dict) else {},
    )
    return prepared


def _parsed_asset_kind(raw: Any) -> ImageAssetKind | None:
    if isinstance(raw, ImageAssetKind):
        return raw
    if isinstance(raw, str) and raw in {kind.value for kind in ImageAssetKind}:
        return ImageAssetKind(raw)
    return None


def _parsed_video_asset_kind(raw: Any) -> VideoAssetKind | None:
    if isinstance(raw, VideoAssetKind):
        return raw
    if isinstance(raw, str) and raw in {kind.value for kind in VideoAssetKind}:
        return VideoAssetKind(raw)
    return None


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
    # Settings picked from the scene library. Their reference stills/clips are
    # merged into `reference_asset_ids` in `scenes.service.apply_scene_refs`,
    # sharing the same 9-slot budget with `character_ids`' references above.
    scene_ids: list[str] = Field(default_factory=list, max_length=4)
    # Which `CreationSkill`s (if any) the client applied to this request, in
    # pick order. Not trusted blindly: the `skill_context` workflow node
    # re-fetches and re-merges each skill's own params server-side before
    # generation runs.
    skill_ids: list[str] = Field(default_factory=list, max_length=5)
    # Platform-curated style catalogue entry. Single and mutually exclusive —
    # unlike `skill_ids`. The same `skill_context` node re-fetches it so a
    # bare API client that never merged locally still gets `prompt_suffix`.
    style_gallery_id: str | None = Field(default=None, max_length=40)
    # What a `text_to_image`/`image_to_image` output is *for* — orthogonal to
    # `operation`. Selects both which `GenerationWorkflowTemplate` runs
    # (`workflow_templates_service.get_active`) and, for `CHARACTER`/`SCENE`,
    # which asset the successful output(s) auto-attach to
    # (`app.workflows.nodes.execute_asset_output_link`). Meaningless (and
    # rejected — see `validate_generation_params`) for any other operation.
    asset_kind: ImageAssetKind = ImageAssetKind.GENERAL
    # Only meaningful when `asset_kind == CHARACTER`: which of front/side/back
    # this job produces, one at a time (`app.workflows.nodes
    # .execute_asset_output_advance` loops the shared graph back to
    # `asset_planning` between each). Defaults to `["front"]` when omitted —
    # a plain single-view request. A "补全侧面/背面" completion request names
    # `["side", "back"]` explicitly, producing both from one job.
    character_views: list[CharacterViewAngle] | None = Field(default=None, max_length=3)
    # The character skill / scene to auto-attach this job's output(s) to, for
    # `asset_kind == CHARACTER` / `== SCENE` respectively. Left unset, a
    # `CHARACTER` job creates a brand-new character skill named after the
    # plan's subject instead of updating an existing one.
    target_character_id: str | None = Field(default=None, max_length=40)
    target_scene_id: str | None = Field(default=None, max_length=40)
    # Overrides the planner's own guessed `subject_name` when auto-creating a
    # new character/scene skill (no `target_character_id`/`target_scene_id`).
    # Only meaningful for a caller that already knows the exact name — e.g.
    # the script studio's "生成角色图/场景图" jump-out, which carries the
    # script's own character name/scene heading rather than letting the
    # planner guess one from the prompt. Ignored once a target id is set
    # (there's nothing to name), and ignored for `asset_kind == GENERAL`.
    subject_name_hint: str | None = Field(default=None, max_length=60)
    # Lets the client opt out of `execute_asset_output_link` entirely — e.g.
    # borrowing an existing character's front view for side/back consistency
    # without also writing the new output back into that character's roster.
    # Ignored (treated as `True`) when `asset_kind` is `GENERAL`, since that
    # node is already a no-op in that case. Shared by the video asset-kind
    # path too (`video_asset_kind` below) via the same
    # `execute_asset_output_link` opt-out check.
    auto_attach_asset: bool = True
    # What a `text_to_video`/`image_to_video`/`video_to_video` output is
    # *for* — the video-side equivalent of `asset_kind` above, orthogonal to
    # `operation` the same way. Selects both which `GenerationWorkflowTemplate`
    # runs and, for `CHARACTER_ACTION`/`SCENE`, which character/scene the
    # successful output auto-attaches to as a clip (`action_clips`/`clips`,
    # not `reference_assets` — see `app.workflows.nodes._link_character_action_output`
    # / `_link_scene_clip_output`). Deliberately a separate field/enum from
    # `asset_kind` rather than a shared one: video has no `CharacterViewAngle`
    # multi-view loop, and mixing the two into one field would let a video
    # job's kind value collide with an image kind's string in any lookup
    # keyed by bare `asset_kind` string (see `VideoAssetKind`'s docstring).
    # Meaningless (and rejected — see `validate_generation_params`) for any
    # non-video operation.
    video_asset_kind: VideoAssetKind = VideoAssetKind.GENERAL
    extra: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _character_views_scoped_to_character_kind(self) -> GenerationParams:
        if self.asset_kind != ImageAssetKind.CHARACTER:
            if self.character_views:
                raise ValueError("character_views 仅适用于 asset_kind=character。")
            return self
        views = self.character_views or [CharacterViewAngle.FRONT]
        deduped: list[CharacterViewAngle] = []
        for view in views:
            if view == CharacterViewAngle.GENERAL:
                raise ValueError("character_views 只能是 front/side/back。")
            if view not in deduped:
                deduped.append(view)
        # Canonical order regardless of what the caller listed, matching
        # `execute_asset_output_advance`'s own front → side → back walk.
        self.character_views = [view for view in CHARACTER_JOB_VIEWS if view in deduped]
        return self


class QuoteRequest(ApiModel):
    operation: Operation
    quality_tier: QualityTier
    duration_seconds: int = Field(default=0, ge=0, le=MAX_GENERATION_DURATION_SECONDS)
    # Same fields `GenerationParams` carries — optional here so a quote taken
    # before the rest of the form is filled in still prices correctly.
    # `character_views` having more than one entry is what makes a "补全
    # 侧面/背面" completion job cost more than one image (see `pricing.quote`).
    asset_kind: ImageAssetKind = ImageAssetKind.GENERAL
    character_views: list[CharacterViewAngle] | None = Field(default=None, max_length=3)


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
        validate_generation_params(
            self.operation,
            duration_seconds=self.params.duration_seconds,
            aspect_ratio=self.params.aspect_ratio,
            reference_asset_ids=self.params.reference_asset_ids,
            character_ids=self.params.character_ids,
            scene_ids=self.params.scene_ids,
            video_options=self.params.video_options,
            asset_kind=self.params.asset_kind,
            video_asset_kind=self.params.video_asset_kind,
            extra=self.params.extra,
        )
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
    # Micro-USD (1e-6 USD): a typical call's retry-amplified cost, and what
    # this particular request was projected to cost.
    effective_cost_micro_usd: int = 0
    estimated_cost_micro_usd: int = 0
    # Both figures came from a built-in prior, not a configured price.
    cost_is_estimated: bool = False


class JobEventResponse(ApiModel):
    sequence: int
    event_type: str
    status: JobStatus
    progress: int
    message: str
    internal_code: str | None = None
    created_at: dt.datetime
    # Which graph node actually wrote this event (see `zaolang-generation-jobs`
    # invariant #13). Already carried by the admin stream; exposed here too so
    # a multi-view `CHARACTER` job's client can tell an `asset_planning` re-entry
    # (one per produced view) apart from every other `planning`-type event,
    # without matching on `message` text.
    node_id: str | None = None


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
    # Every asset the job produced, in generation order — `output_asset_id`/
    # `output_url` above are always this list's first entry. `None` for the
    # overwhelming majority of jobs that only ever made one asset; more than
    # one only for an `asset_kind=character` job whose `character_views`
    # named more than one view (see `execute_asset_output_advance`).
    output_asset_ids: list[str] | None = None
    output_urls: list[str] | None = None
    # Echoes `GenerationParams.asset_kind` back so a client can, e.g., offer
    # "save as a shareable cover skill" on a succeeded `cover` job's detail
    # page without having kept the original request around.
    asset_kind: ImageAssetKind | None = None
    # Echoes `GenerationParams.video_asset_kind` back — the video-side
    # equivalent of `asset_kind` above, `None` for every non-video operation.
    video_asset_kind: VideoAssetKind | None = None
    # Echoes `GenerationParams.character_views` back — only meaningful with
    # `asset_kind=character`. Lets a client show upfront how many views this
    # job produces (e.g. "第 2/3 张") without re-deriving it from the event
    # stream, and to label `output_asset_ids`/`output_urls`' entries, which
    # are recorded in the same front → side → back order as this list.
    character_views: list[CharacterViewAngle] | None = None
    # Which character/scene skill this job's output actually landed on —
    # the target the client passed, or the id of a skill
    # `execute_asset_output_link` auto-created. `None` for `GENERAL`/`COVER`
    # jobs and for one that never reached settlement. At most one of the two
    # is ever set. The script studio's "返回文案创作" jump-back reads this to
    # auto-relink without the user re-picking from `ScriptLinkPicker`.
    linked_character_id: str | None = None
    linked_scene_id: str | None = None
    draft_id: str | None = None
    # Echoes `GenerationParams.prompt` back. Lets a client (the image studio's
    # inline version-history strip) show what prompt produced each past
    # iteration without keeping a separate client-side copy of the request.
    prompt: str | None = None
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
            r"|style_gallery_cover|editor_source|editor_export|caption|font)$"
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
    updated_at: dt.datetime


class ReportCreateRequest(ApiModel):
    subject_type: str = Field(pattern=r"^(work|asset|user|comment)$")
    subject_id: str
    reason: str
    detail: str | None = Field(default=None, max_length=2000)
