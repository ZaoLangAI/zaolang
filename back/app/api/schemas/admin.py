"""Back-office payloads.

Console responses are deliberately wider than consumer ones: an operator needs
internal codes and raw state that must never leak to a public endpoint.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from pydantic import Field

from app.api.schemas.common import ApiModel
from app.models.enums import (
    CreationSkillCategory,
    CreationSkillStatus,
    CreationSkillVisibility,
    ImageAssetKind,
    JobOrigin,
    JobStatus,
    LearnPostStatus,
    MediaType,
    ModerationStatus,
    Operation,
    RedemptionCodeKind,
    UserStatus,
)
from app.platform_config.schemas import MediaProtocol


class DangerousAction(ApiModel):
    """Base for anything requiring a typed reason.

    The reason is stored in the audit log, so an empty string is refused at the
    schema boundary rather than deep inside a service.
    """

    reason: str = Field(min_length=4, max_length=500)
    confirm: bool = False


class AdminSessionResponse(ApiModel):
    access_token: str
    token_type: str = "Bearer"
    expires_at: dt.datetime
    user_id: str
    email: str
    roles: list[str]
    max_role: str


class ServiceHealth(ApiModel):
    name: str
    healthy: bool
    detail: str = ""
    latency_ms: float | None = None


class QueueDepth(ApiModel):
    queue: str
    depth: int
    consumers: int = 0


class SystemHealthResponse(ApiModel):
    services: list[ServiceHealth]
    queues: list[QueueDepth]
    alembic_revision: str | None = None
    llm_reachable: bool
    app_version: str
    generated_at: dt.datetime


class AdminJobSummary(ApiModel):
    id: str
    user_id: str
    # Resolved from the user's `Profile`; `None` only if the profile row is
    # somehow missing. The frontend falls back to `user_id` when both are
    # `None`, and always keeps the raw id available in a tooltip.
    user_display_name: str | None = None
    user_handle: str | None = None
    status: JobStatus
    operation: str
    quality_tier: str
    origin: JobOrigin = JobOrigin.USER
    # Raw routing key (`f"{endpoint_id}:{capability}"` or a test fixture's
    # provider name) — kept for filtering/replay comparison, but never shown
    # as the primary label; see `provider_label`.
    provider: str | None = None
    # Human-readable form of `provider` (`LlmProviderEndpoint.name`), when the
    # endpoint it names still exists in the current `llm_providers` config.
    provider_label: str | None = None
    routing_reason: str | None = None
    quoted_credits: int
    actual_credits: int | None = None
    attempt_count: int = 0
    failure_code: str | None = None
    created_at: dt.datetime
    finished_at: dt.datetime | None = None
    # `True` when a live `AsyncProviderTask` is well past its own deadline —
    # the poller has not (yet) given up on it. Surfaced so an operator does
    # not have to remember to check `stuck_only` to notice.
    stuck: bool = False
    # The workflow template this job actually pinned at submission/first run
    # (see `workers/pipeline.py::resolve_graph`). `None` for a job that has
    # not started running yet, or for a legacy row predating this column.
    # The frontend uses it to ask `/v1/admin/workflow` for the exact graph
    # this job ran, instead of whatever is active for the operation today.
    workflow_template_id: str | None = None


class JobStatsView(ApiModel):
    """Aggregate job throughput for the statistics hub — not one job's detail."""

    generated_at: dt.datetime
    window_hours: int
    by_status: dict[str, int] = Field(default_factory=dict)
    by_operation: dict[str, int] = Field(default_factory=dict)
    total_jobs: int = 0
    avg_completion_ms: float | None = None


# --- Daily time series for the statistics module's trend charts ------------
#
# Every `*_timeseries` endpoint returns a dense, gap-filled list of daily
# points covering `[today - window_days + 1, today]` in UTC — a day with zero
# activity still appears with zero values so a line chart never jumps.


class JobsDailyPoint(ApiModel):
    date: dt.date
    total: int = 0
    succeeded: int = 0
    failed: int = 0
    avg_completion_ms: float | None = None


class JobsTimeseriesView(ApiModel):
    generated_at: dt.datetime
    window_days: int
    points: list[JobsDailyPoint] = Field(default_factory=list)


class ProviderDailyPoint(ApiModel):
    date: dt.date
    attempts: int = 0
    successes: int = 0
    avg_latency_ms: float | None = None
    total_cost_minor: int = 0


class ProviderTimeseriesView(ApiModel):
    generated_at: dt.datetime
    window_days: int
    points: list[ProviderDailyPoint] = Field(default_factory=list)


class AgentDailyPoint(ApiModel):
    date: dt.date
    runs: int = 0
    degraded_runs: int = 0
    total_tokens: int = 0
    avg_latency_ms: float | None = None


class AgentTimeseriesView(ApiModel):
    generated_at: dt.datetime
    window_days: int
    points: list[AgentDailyPoint] = Field(default_factory=list)


class CreditFlowDailyPoint(ApiModel):
    date: dt.date
    granted: int = 0
    purchased: int = 0
    captured: int = 0
    refunded: int = 0
    royalty_out: int = 0
    royalty_in: int = 0
    access_out: int = 0
    access_in: int = 0
    adjustment: int = 0
    # Sum of every ledger entry's signed amount that day — a sanity total,
    # not a KPI on its own (reserve/release net to zero over time).
    net: int = 0


class CreditFlowTimeseriesView(ApiModel):
    generated_at: dt.datetime
    window_days: int
    points: list[CreditFlowDailyPoint] = Field(default_factory=list)


class ContentDailyPoint(ApiModel):
    date: dt.date
    published_works: int = 0
    remix_edges: int = 0


class ContentTimeseriesView(ApiModel):
    generated_at: dt.datetime
    window_days: int
    points: list[ContentDailyPoint] = Field(default_factory=list)


class UserGrowthDailyPoint(ApiModel):
    date: dt.date
    new_users: int = 0


class UserGrowthTimeseriesView(ApiModel):
    """Registrations are a real daily series; suspensions are not — `User`
    has no `suspended_at`, so a suspension trend would be fabricated. The
    suspended count is a current snapshot instead."""

    generated_at: dt.datetime
    window_days: int
    points: list[UserGrowthDailyPoint] = Field(default_factory=list)
    total_users: int = 0
    suspended_users: int = 0


class CostDailyPoint(ApiModel):
    """One day of model spend, in micro-USD (1e-6 USD) integers.

    Micro rather than cents because vendor prices go far below a cent; the
    console divides by 1_000_000 to display dollars. This is what we pay
    vendors — unrelated to the credits a user spends.
    """

    date: dt.date
    llm_micro_usd: int = 0
    media_micro_usd: int = 0
    total_micro_usd: int = 0


class CostTimeseriesView(ApiModel):
    generated_at: dt.datetime
    window_days: int
    points: list[CostDailyPoint] = Field(default_factory=list)
    total_micro_usd: int = 0


class ProviderCostSeriesView(ApiModel):
    """One endpoint's daily spend. A media endpoint's per-capability attempts
    are rolled back up to the endpoint, because that is what gets billed."""

    endpoint_id: str
    endpoint_name: str = ""
    total_micro_usd: int = 0
    points: list[CostDailyPoint] = Field(default_factory=list)


class ModelCostView(ApiModel):
    """Window total for one model. Cumulative rather than a trend: with more
    than a handful of models configured, per-model lines stop being legible."""

    model: str
    endpoint_id: str = ""
    endpoint_name: str = ""
    kind: Literal["general", "media"] = "general"
    calls: int = 0
    total_micro_usd: int = 0


class CostBreakdownView(ApiModel):
    generated_at: dt.datetime
    window_days: int
    providers: list[ProviderCostSeriesView] = Field(default_factory=list)
    models: list[ModelCostView] = Field(default_factory=list)


class ProviderAttemptView(ApiModel):
    id: str
    attempt_number: int
    provider: str
    status: str
    latency_ms: int | None = None
    cost_credits: int | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: dt.datetime


class JobEventView(ApiModel):
    sequence: int
    event_type: str
    status: str
    progress: int
    message: str
    internal_code: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    # The graph node that emitted this event, or `None` for events recorded
    # before this column existed. `workflow-steps.tsx` matches on this first
    # and only falls back to guessing from `event_type` when it is absent.
    node_id: str | None = None
    created_at: dt.datetime


class AgentRunView(ApiModel):
    id: str
    agent_name: str
    # Which agent and prompt slot served this call. Null for runs recorded
    # before agent profiles existed.
    agent_profile_id: str | None = None
    # Resolved `AgentProfile.display_name`. `None` when `agent_profile_id`
    # is null or the profile was since deleted — the frontend falls back to
    # `agent_name` (the role string) in that case.
    agent_display_name: str | None = None
    prompt_slot: str | None = None
    model: str
    mode: str
    degraded: bool
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    latency_ms: int | None = None
    status: str
    error_message: str | None = None
    job_id: str | None = None
    # The graph node whose executor made this call, or `None` for runs
    # predating this column or made outside a workflow run.
    node_id: str | None = None
    input_json: dict[str, Any] | None = None
    output_json: dict[str, Any] = Field(default_factory=dict)
    thinking_text: str = ""
    created_at: dt.datetime


class AsyncProviderTaskView(ApiModel):
    """One in-flight external render, surfaced so an operator can see what a
    `RUNNING` job with no Celery task in flight is actually waiting on."""

    node_id: str
    capability_name: str
    provider_label: str | None = None
    external_task_id: str
    poll_count: int
    next_poll_at: dt.datetime
    deadline_at: dt.datetime
    claimed_at: dt.datetime | None = None
    provider_attempt_id: str | None = None


class AdminJobDetail(AdminJobSummary):
    """Full replay material for one job."""

    params: dict[str, Any] = Field(default_factory=dict)
    routing_trace: list[dict[str, Any]] = Field(default_factory=list)
    events: list[JobEventView] = Field(default_factory=list)
    attempts: list[ProviderAttemptView] = Field(default_factory=list)
    agent_runs: list[AgentRunView] = Field(default_factory=list)
    # `None` once the render finishes (success, failure, timeout) or if the
    # job never suspended on an external task at all.
    async_task: AsyncProviderTaskView | None = None
    # Short-lived signed URL of `output_asset_id`, for the sandbox inspector
    # and the jobs-console replay. `None` until quality registers an asset.
    preview_url: str | None = None
    mime_type: str | None = None


class JobTerminateRequest(DangerousAction):
    release_credits: bool = True


class ProviderStatView(ApiModel):
    provider: str
    operation: str
    quality_tier: str
    attempts: int
    successes: int
    success_rate: float
    p50_latency_ms: int
    p95_latency_ms: int
    # Average micro-USD (1e-6 USD) actually spent per successful generation.
    effective_cost_micro_usd: int
    enabled: bool


class RoutingReplayResponse(ApiModel):
    job_id: str
    chosen_provider: str | None = None
    candidates: list[dict[str, Any]] = Field(default_factory=list)


class AgentUsageSummary(ApiModel):
    agent_name: str
    runs: int
    degraded_runs: int
    total_tokens: int
    avg_latency_ms: int


class ModerationQueueView(ApiModel):
    id: str
    subject_type: str
    subject_id: str
    stage: str
    status: ModerationStatus
    priority: int
    reason_code: str | None = None
    claimed_by_user_id: str | None = None
    preview_title: str | None = None
    preview_url: str | None = None
    preview_media_type: str | None = None
    owner_display_name: str | None = None
    owner_handle: str | None = None
    created_at: dt.datetime


class ModerationDecisionRequest(ApiModel):
    decision: Literal["approved", "rejected", "needs_review"]
    reason_code: str | None = Field(default=None, max_length=64)
    note: str | None = Field(default=None, max_length=1000)
    public_message: str | None = Field(default=None, max_length=500)


class ModerationHistoryEntry(ApiModel):
    """One row from the append-only verdict trail for a subject."""

    id: str
    stage: str
    status: ModerationStatus
    decided_by: str
    reviewer_user_id: str | None = None
    reason_code: str | None = None
    categories: list[str] = Field(default_factory=list)
    public_message: str | None = None
    created_at: dt.datetime


class ModerationWorkDetailView(ApiModel):
    id: str
    title: str
    description: str | None = None
    prompt: str | None = None
    cover_url: str | None = None
    media_url: str | None = None
    media_type: str | None = None
    owner_user_id: str
    owner_display_name: str | None = None
    owner_handle: str | None = None
    visibility: str
    lifecycle_status: str
    tombstone_reason: str | None = None
    hide_reason: str | None = None
    created_at: dt.datetime


class ModerationSubjectDetailView(ApiModel):
    """Full context for one queue item: the current decision plus everything
    that led to it, so a reviewer can judge a REJECTED/HIDDEN call without
    trusting the summary row alone."""

    queue_item: ModerationQueueView
    history: list[ModerationHistoryEntry]
    work: ModerationWorkDetailView | None = None
    skill: CreationSkillAdminView | None = None
    job: ModerationJobDetailView | None = None
    # Open reports naming the same subject — a reviewer acting purely off the
    # agent's flag should still see whether users have separately complained.
    open_report_count: int = 0


class ModerationJobDetailView(ApiModel):
    """A generation_job queue subject: prompt, sandbox origin, and output."""

    id: str
    origin: JobOrigin
    operation: str
    quality_tier: str
    status: JobStatus
    prompt: str | None = None
    preview_url: str | None = None
    mime_type: str | None = None
    created_at: dt.datetime


class ReportCaseView(ApiModel):
    id: str
    reporter_user_id: str | None = None
    subject_type: str
    subject_id: str
    reason: str
    detail: str | None = None
    status: str
    resolution_note: str | None = None
    handled_by_user_id: str | None = None
    handled_by_display_name: str | None = None
    handled_at: dt.datetime | None = None
    # Populated only when subject_type == "work" — the only subject type any
    # client actually creates reports against today.
    subject: ModerationWorkDetailView | None = None
    # How many other still-open reports name this same subject.
    open_report_count: int = 0
    created_at: dt.datetime


class ReportResolveRequest(ApiModel):
    status: Literal["resolved", "rejected", "escalated"]
    resolution_note: str = Field(min_length=1, max_length=1000)


class TombstoneRequest(DangerousAction):
    pass


class AppealAdminView(ApiModel):
    id: str
    work_id: str
    owner_user_id: str
    owner_display_name: str | None = None
    owner_handle: str | None = None
    reason: str
    status: str
    decision_note: str | None = None
    decided_by_user_id: str | None = None
    decided_by_display_name: str | None = None
    decided_at: dt.datetime | None = None
    source_report_id: str | None = None
    subject: ModerationWorkDetailView | None = None
    open_report_count: int = 0
    created_at: dt.datetime


class AppealDecisionRequest(ApiModel):
    decision: Literal["granted", "denied"]
    decision_note: str = Field(min_length=1, max_length=1000)


class LearnPostAdminView(ApiModel):
    id: str
    author_user_id: str
    title: str
    summary: str
    level: str
    status: LearnPostStatus
    cover_url: str | None = None
    body_markdown: str = ""
    asset_urls: dict[str, str] = Field(default_factory=dict)
    reject_reason: str | None = None
    created_at: dt.datetime


class LearnPostDecisionRequest(ApiModel):
    """`reason` 拒绝时必填，通过时忽略——校验放在 domain 层，见 `learning.service.reject`。"""

    reason: str | None = None


class CharacterReferenceAssetAdminView(ApiModel):
    asset_id: str
    view: str = "general"
    label: str | None = None
    url: str | None = None


class CreationSkillAdminView(ApiModel):
    id: str
    owner_user_id: str
    title: str
    description: str
    category: CreationSkillCategory
    cover_url: str | None = None
    cover_media_type: MediaType | None = None
    applicable_operations: list[Operation] = Field(default_factory=list)
    visibility: CreationSkillVisibility
    status: CreationSkillStatus
    usage_count: int
    access_credits: int = 0
    reject_reason: str | None = None
    created_at: dt.datetime
    # Populated only when `category == CHARACTER` — a reviewer needs to see
    # every reference image (not just `cover_url`) and confirm portrait
    # consent was actually captured before approving a public character.
    character_reference_assets: list[CharacterReferenceAssetAdminView] = Field(default_factory=list)
    character_portrait_consent_at: dt.datetime | None = None
    # Populated only when `category == SCENE_ASSET` — same rationale as
    # `character_reference_assets` above, minus the portrait-consent field a
    # setting has no use for.
    scene_reference_assets: list[CharacterReferenceAssetAdminView] = Field(default_factory=list)


class FingerprintDuplicateGroup(ApiModel):
    fingerprint: str
    asset_ids: list[str]
    owner_user_ids: list[str]
    first_seen_at: dt.datetime


class AdminUserView(ApiModel):
    id: str
    email: str
    handle: str | None = None
    display_name: str | None = None
    status: UserStatus
    roles: list[str]
    region: str
    available_credits: int = 0
    reserved_credits: int = 0
    work_count: int = 0
    created_at: dt.datetime
    last_login_at: dt.datetime | None = None


class SuspendRequest(DangerousAction):
    pass


class RoleGrantRequest(DangerousAction):
    roles: list[str] = Field(min_length=1, max_length=6)


class AdjustCreditsRequest(DangerousAction):
    amount: int = Field(description="正数为补发，负数为扣回。")
    idempotency_key: str | None = None


class LedgerEntryView(ApiModel):
    id: str
    account_id: str
    user_id: str
    type: str
    amount: int
    balance_after: int
    reserved_after: int
    job_id: str | None = None
    reason: str | None = None
    actor_user_id: str | None = None
    created_at: dt.datetime


class DanglingReserveView(ApiModel):
    job_id: str
    user_id: str
    amount: int
    reserved_at: dt.datetime
    age_hours: float
    job_status: str


class ReconciliationView(ApiModel):
    generated_at: dt.datetime
    account_count: int
    mismatched_account_count: int
    dangling_reserved_count: int
    details: dict[str, Any] = Field(default_factory=dict)


class RedemptionCodeCreateRequest(DangerousAction):
    """Confirmation + a written reason, like `AdjustCreditsRequest` — minting
    a code is a direct promise of real credits."""

    kind: RedemptionCodeKind = RedemptionCodeKind.PROMO
    credits: int = Field(gt=0)
    max_uses: int = Field(default=1, gt=0)
    expires_at: dt.datetime | None = None
    note: str | None = Field(default=None, max_length=300)
    code: str | None = Field(default=None, min_length=4, max_length=32)


class RedemptionCodeView(ApiModel):
    id: str
    code: str
    kind: RedemptionCodeKind
    credits: int
    max_uses: int
    used_count: int
    expires_at: dt.datetime | None = None
    is_active: bool
    note: str | None = None
    created_by_user_id: str | None = None
    created_at: dt.datetime


class RedemptionRecordView(ApiModel):
    id: str
    user_id: str
    credits: int
    created_at: dt.datetime


class ConfigVersionView(ApiModel):
    id: str
    key: str
    version: int
    is_active: bool
    note: str | None = None
    created_by_user_id: str | None = None
    created_at: dt.datetime


class ConfigValueResponse(ApiModel):
    key: str
    version: int
    value: dict[str, Any]
    schema_fields: list[str] = Field(default_factory=list)


class ConfigUpdateRequest(ApiModel):
    value: dict[str, Any]
    note: str = Field(min_length=1, max_length=300)


class ConfigRollbackRequest(DangerousAction):
    target_version: int


class ConfigDiffEntry(ApiModel):
    path: str
    before: Any = None
    after: Any = None


class ConfigDiffResponse(ApiModel):
    key: str
    from_version: int
    to_version: int
    entries: list[ConfigDiffEntry]


class TokenPricingPayload(ApiModel):
    """`kind="general"` list price, in micro-USD (1e-6 USD) per million tokens.

    $0.060 per million is 60_000 here. Integers rather than a decimal string
    so the contract has one representation; the console does the conversion
    from what an operator types in dollars.
    """

    input_per_million_micro_usd: int = Field(default=0, ge=0)
    output_per_million_micro_usd: int = Field(default=0, ge=0)


class ImagePricingPayload(ApiModel):
    input_per_image_micro_usd: int = Field(default=0, ge=0)
    generation_per_image_micro_usd: int = Field(default=0, ge=0)


class AudioPricingPayload(ApiModel):
    per_10k_characters_micro_usd: int = Field(default=0, ge=0)


class VideoPricingPayload(ApiModel):
    """Keyed by output resolution, because vendors price 2K and 768P apart."""

    generation_per_second_micro_usd: dict[str, int] = Field(default_factory=dict)
    input_material_per_second_micro_usd: dict[str, int] = Field(default_factory=dict)
    reference_image_free_count: int = Field(default=5, ge=0, le=100)
    extra_reference_image_micro_usd: int = Field(default=0, ge=0)


class MediaPricingPayload(ApiModel):
    """Sections a media endpoint's capabilities do not cover are dropped
    server-side, so a stale price cannot outlive the capability it billed."""

    image: ImagePricingPayload | None = None
    audio: AudioPricingPayload | None = None
    video: VideoPricingPayload | None = None


class LlmProviderEndpointView(ApiModel):
    """Read model for one model-provider endpoint.

    `api_key` itself never appears here — only whether one is set and a
    truncated preview — so a GET response is always safe to render or log.

    `role`/`backup_order` and concurrency are meaningful for `general` only.
    For media, `capabilities` is derived and read-only from the declared
    `model` + `input_modalities`/`output_modalities`.
    """

    id: str
    name: str
    base_url: str
    api_key_configured: bool
    api_key_preview: str | None = None
    kind: Literal["general", "media"] = "general"
    # The one model id this endpoint serves, whatever its kind.
    model: str = ""
    input_modalities: list[str] = Field(default_factory=list)
    output_modalities: list[str] = Field(default_factory=list)
    # `kind="media"` only: HTTP contract name (openai / minimax / …).
    protocol: MediaProtocol | None = None
    # Derived from the modalities above; read-only.
    capabilities: list[str] = Field(default_factory=list)
    max_concurrency: int
    role: Literal["primary", "backup"]
    backup_order: int
    timeout_ms: int
    enabled: bool
    # `kind="general"` only. 0 means undeclared, shown as unknown rather than
    # enforced — the provider is the authority on its own ceiling.
    context_length: int = 0
    max_output_tokens: int = 0
    token_pricing: TokenPricingPayload = Field(default_factory=TokenPricingPayload)
    # `kind="media"` only.
    media_pricing: MediaPricingPayload = Field(default_factory=MediaPricingPayload)
    concurrency_in_use: int = 0
    circuit_breaker_open: bool = False
    recent_attempts: int = 0
    recent_success_rate: float | None = None


class LlmProviderCategoryView(ApiModel):
    """Legacy category projection; the console now renders a flat endpoint
    list from `LlmProviderPoolView.endpoints`. Kept so older clients do not
    break on an unexpected schema change."""

    category: str
    kind: Literal["general", "media"]
    primary: LlmProviderEndpointView | None = None
    backups: list[LlmProviderEndpointView] = Field(default_factory=list)


class LlmProviderPoolView(ApiModel):
    endpoints: list[LlmProviderEndpointView] = Field(default_factory=list)
    categories: list[LlmProviderCategoryView] = Field(default_factory=list)
    # Endpoint ids demoted from primary to backup by the most recent upsert,
    # surfaced once so the console can show a non-silent toast for it.
    demoted_endpoint_ids: list[str] = Field(default_factory=list)


class LlmProviderValidationResult(ApiModel):
    endpoint_id: str
    kind: Literal["general", "media"]
    target_model: str | None = None
    probe_type: str
    reachable: bool
    usable: bool
    latency_ms: int
    provider_status_code: int | None = None
    error_code: str | None = None
    warning_code: str | None = None
    provider_error_code: str | None = None
    provider_error_message: str | None = None
    external_task_id: str | None = None


class LlmProviderValidationJob(ApiModel):
    """A connectivity probe that outlives the HTTP request that started it.

    Image and audio checks can take tens of seconds; the console starts this
    job, then polls until `status` is `completed` rather than holding one
    request open for the whole upstream generation.
    """

    validation_id: str
    status: Literal["running", "completed"]
    elapsed_ms: int
    timeout_ms: int
    result: LlmProviderValidationResult | None = None


class LlmProviderEndpointUpsertRequest(ApiModel):
    name: str = Field(min_length=1, max_length=100)
    base_url: str = Field(min_length=1, max_length=500)
    # None keeps the stored key unchanged; "" clears it; anything else replaces it.
    api_key: str | None = None
    kind: Literal["general", "media"] = "general"
    role: Literal["primary", "backup"] = "backup"
    backup_order: int = Field(default=100, ge=1, le=1000)
    # The one model id this endpoint serves, required for both kinds. For
    # media it pairs with the modalities below; capability tags are derived
    # server-side, not submitted here.
    model: str = Field(min_length=1, max_length=200)
    input_modalities: list[str] = Field(default_factory=list)
    output_modalities: list[str] = Field(default_factory=list)
    # `kind="media"` only. Null lets the domain schema infer from modalities.
    protocol: MediaProtocol | None = None
    max_concurrency: int = Field(default=4, ge=1, le=256)
    timeout_ms: int = Field(default=30_000, ge=1_000, le=120_000)
    enabled: bool = True
    context_length: int = Field(default=0, ge=0, le=100_000_000)
    max_output_tokens: int = Field(default=0, ge=0, le=10_000_000)
    token_pricing: TokenPricingPayload = Field(default_factory=TokenPricingPayload)
    media_pricing: MediaPricingPayload = Field(default_factory=MediaPricingPayload)


class PromptSlotView(ApiModel):
    """One of the system prompts a role owns.

    Most roles have exactly one; `intent_router` and `copy` each make two
    unrelated calls under a single agent identity, and each needs its own
    prompt chain.
    """

    key: str
    label: str
    description: str = ""


class RolePresetView(ApiModel):
    """One role an operator may create an agent for.

    A code-maintained catalogue rather than a table: a role only runs if some
    node type invokes it, so free-text roles would produce agents that never
    execute. `category` drives which half of the create form applies only
    semantically — both `judgment` and `assist` bind one LLM model the same
    way.
    """

    role: str
    display_name: str
    category: Literal["judgment", "assist"]
    description: str = ""
    operations: list[str] = Field(default_factory=list)
    default_template_key: str | None = None
    sort_order: int = 0
    # False once an `AgentNode` row exists for this role, so the console can
    # tell "brand new role" from "role already in the topology".
    is_new: bool = True


class AgentNodeView(ApiModel):
    """One pipeline stage plus which failover-pool endpoints could serve it.

    `candidate_endpoint_ids` is derived, not stored: it is whichever
    `llm_providers` endpoints are enabled `kind="general"` endpoints — every
    agent role shares that one pool now — so the node graph can show "0
    candidate endpoints" as an actionable warning rather than a silent gap.
    """

    id: str
    role: str
    display_name: str
    description: str
    category: Literal["judgment", "assist"] = "judgment"
    enabled: bool
    sort_order: int
    candidate_endpoint_ids: list[str] = Field(default_factory=list)
    prompt_slots: list[PromptSlotView] = Field(default_factory=list)


class AgentProfileView(ApiModel):
    """One agent. Its `role` says which pipeline stage it can run.

    `operations` is the agent's declared capability — the operations its
    prompts were written for. Empty means general purpose. `used_by_operations`
    is derived from the currently active workflow templates, so the console
    can show at a glance whether an agent is actually wired up and whether
    it is being used outside what it declares.
    """

    id: str
    role: str
    key: str
    display_name: str
    description: str
    category: Literal["judgment", "assist"] = "judgment"
    operations: list[str] = Field(default_factory=list)
    is_default: bool
    # Only ever set on a `copy`-role profile — which `ImageAssetKind` bucket
    # "AI 润色" routes to this agent for. `None` means this agent is not a
    # kind-specific default (it may still be the role's ordinary default).
    default_for_asset_kind: Literal["character", "scene", "cover"] | None = None
    enabled: bool
    # Null means the agent draws from the shared `kind="general"` pool,
    # which is what every agent did before per-agent bindings existed.
    default_endpoint_id: str | None = None
    backup_endpoint_id: str | None = None
    # Read-only, derived from `default_endpoint_id`: an endpoint declares
    # exactly one model, so binding the provider is what picks the model.
    model: str | None = None
    max_tokens: int | None = None
    temperature: float | None = None
    reasoning_model: bool | None = None
    used_by_operations: list[str] = Field(default_factory=list)
    created_at: dt.datetime


class AgentProfileCreateRequest(ApiModel):
    # Validated against `ROLE_PRESETS` in the domain service rather than here:
    # a role that already has an `AgentNode` row stays usable even after its
    # preset leaves the catalogue, and only the service can see that.
    role: str = Field(min_length=1, max_length=40)
    # A stable operator-facing handle, unique within the role. Graphs bind by
    # id, not by this, so it is safe to read in logs without being load
    # bearing; it stays immutable anyway so audit history keeps lining up.
    key: str = Field(min_length=1, max_length=40, pattern=r"^[a-z0-9][a-z0-9-]*$")
    display_name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=2_000)
    operations: list[str] = Field(default_factory=list)
    default_endpoint_id: str | None = Field(default=None, max_length=64)
    backup_endpoint_id: str | None = Field(default=None, max_length=64)
    # No model here on purpose: an endpoint serves exactly one model, so the
    # provider pin picks it. No max_tokens/temperature either: sampling is a
    # generic runtime fallback, not an operator input or a per-model table.
    reasoning_model: bool | None = None
    # Validated service-side to only apply to `role == "copy"`; setting it
    # clears whichever other profile previously held that bucket.
    default_for_asset_kind: Literal["character", "scene", "cover"] | None = None


class AgentProfileUpdateRequest(ApiModel):
    """Partial AgentProfile update.

    Endpoint pins use an empty string to clear. `reasoning_model`
    distinguishes omission (keep the current override) from explicit null
    (inherit the role's default Agent).
    """

    display_name: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=2_000)
    operations: list[str] | None = None
    is_default: bool | None = None
    enabled: bool | None = None
    default_endpoint_id: str | None = Field(default=None, max_length=64)
    backup_endpoint_id: str | None = Field(default=None, max_length=64)
    # No model here on purpose: an endpoint serves exactly one model, so the
    # provider pin picks it. No max_tokens/temperature either: sampling is a
    # generic runtime fallback, not an operator input or a per-model table.
    reasoning_model: bool | None = None
    # Omission keeps the current value; explicit `null` clears it; a bucket
    # value promotes this agent and demotes whichever profile held it before
    # — same tri-state distinction as `reasoning_model` above.
    default_for_asset_kind: Literal["character", "scene", "cover"] | None = None


class SkillTemplateView(ApiModel):
    """A starting prompt the skill editor can load.

    Loading one only fills the form: publishing stays a separate confirmed
    action, because the published text is what decides whether content gets
    rejected or a retry spends credits.
    """

    key: str
    label: str
    description: str = ""
    category: Literal["judgment", "assist"]
    prompt_template: str
    tool_grants: list[str] = Field(default_factory=list)
    role: str | None = None
    slot: str = "default"


class AgentSkillView(ApiModel):
    id: str
    node_role: str
    profile_id: str
    slot: str
    version: int
    prompt_template: str
    tool_grants: list[str] = Field(default_factory=list)
    is_active: bool
    created_by_user_id: str | None = None
    reason: str | None = None
    created_at: dt.datetime


class AgentSkillPublishRequest(DangerousAction):
    profile_id: str = Field(min_length=1, max_length=40)
    slot: str = Field(min_length=1, max_length=40)
    prompt_template: str = Field(min_length=1, max_length=20_000)
    tool_grants: list[str] = Field(default_factory=list)


class AgentDebugChatMessage(ApiModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=20_000)


class AgentDebugChatRequest(ApiModel):
    """One turn of prompt-evaluation chat against a real model.

    `prompt_template`, when given, is the skill editor's unsaved draft — the
    whole point of "debug the draft" is trying a prompt before it is ever
    published. Omitted, this debugs whatever is currently active for
    `(profile, slot)`. `messages` is the whole conversation so far, not just
    the newest turn: this is a stateless endpoint, so the console resends
    history on every call the same way it already does for the shortform
    clarify flow.
    """

    slot: str = Field(min_length=1, max_length=40)
    prompt_template: str | None = Field(default=None, max_length=20_000)
    messages: list[AgentDebugChatMessage] = Field(min_length=1, max_length=40)


class AgentDebugChatResponse(ApiModel):
    reply_text: str
    parsed_json: dict[str, Any] | None = None
    degraded: bool
    model: str
    latency_ms: int
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    agent_run_id: str


class AgentSkillToolView(ApiModel):
    """One tool a role's skill may be granted, from `app.agents.tools.AGENT_TOOL_GRANTS`."""

    name: str


class FeatureFlagView(ApiModel):
    name: str
    enabled: bool
    rollout_percent: int = 100
    description: str = ""


class AnnouncementRequest(ApiModel):
    kind: Literal["notice", "maintenance", "incident"] = "notice"
    title_zh: str = Field(min_length=1, max_length=200)
    title_en: str = Field(min_length=1, max_length=200)
    body_zh: str = Field(min_length=1)
    body_en: str = Field(min_length=1)
    starts_at: dt.datetime | None = None
    ends_at: dt.datetime | None = None
    is_published: bool = False
    broadcast: bool = False


class AnnouncementView(ApiModel):
    id: str
    kind: str
    title_zh: str
    title_en: str
    body_zh: str
    body_en: str
    starts_at: dt.datetime
    ends_at: dt.datetime | None = None
    is_published: bool


class AuditLogView(ApiModel):
    id: str
    actor_user_id: str | None = None
    actor_roles: str | None = None
    action: str
    target_type: str
    target_id: str | None = None
    before: dict[str, Any] = Field(default_factory=dict, alias="before_json")
    after: dict[str, Any] = Field(default_factory=dict, alias="after_json")
    reason: str | None = None
    request_id: str | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    created_at: dt.datetime


class LogEntryView(ApiModel):
    """One row in the unified log centre: an `AuditLog` row (privileged writes)
    or a `SystemLog` row (auth/rate-limit/permission signals), reshaped onto a
    common shape so the console can filter and scroll through both together."""

    id: str
    source: str
    level: str
    event: str
    message: str
    actor_user_id: str | None = None
    target: str | None = None
    ip_address: str | None = None
    request_id: str | None = None
    occurrence_count: int | None = None
    reason: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    # The `generation_job` this row is about, for the jobs console's
    # "related logs" section — an audit row's `target_id` when
    # `target_type == "generation_job"`, or a system row's own `job_id`.
    job_id: str | None = None
    occurred_at: dt.datetime


class StorageUsageResponse(ApiModel):
    bucket: str
    object_count: int
    total_bytes: int
    by_prefix: dict[str, int] = Field(default_factory=dict)
    lifecycle_rules: list[dict[str, Any]] = Field(default_factory=list)


class BackupTriggerRequest(DangerousAction):
    kind: Literal["database", "objects"] = "database"


class BackupRecordView(ApiModel):
    id: str
    kind: str
    status: str
    object_key: str | None = None
    size_bytes: int | None = None
    message: str | None = None
    created_at: dt.datetime


class DataRequestView(ApiModel):
    id: str
    user_id: str
    type: str
    status: str
    note: str | None = None
    result_object_key: str | None = None
    created_at: dt.datetime


class DataRequestDecisionRequest(DangerousAction):
    approve: bool = True


class SeedRequest(DangerousAction):
    reset: bool = False


class AgentBindingView(ApiModel):
    """Tells the editor that one config field selects an agent.

    Without this the schema-driven form would render `agent_id` as a
    free-text box; with it the editor can offer the agents that actually
    exist for `role`, which is also the only role this field accepts.
    """

    config_field: str
    role: str
    slot: str


class DynamicAgentBindingView(ApiModel):
    """Tells the editor that one config field selects an agent whose role is
    chosen in a sibling field rather than fixed by the node type.

    `custom_agent` is the only such node type: it exists to run a role that
    was created in the console. The editor renders the three fields as
    cascading dropdowns — role, then the agents having it, then that role's
    prompt slots — instead of three free-text boxes.
    """

    config_field: str
    role_field: str
    slot_field: str


class NodeTypeView(ApiModel):
    """One entry in the admin-facing node palette.

    `config_schema` is the node type's Pydantic config model rendered as a
    JSON Schema, so the editor can generate its property-panel form without a
    hand-maintained mirror of `app.workflows.configs`.
    """

    type: str
    category: str
    # Chinese, from `registry.py`. The console prefers its own translation
    # keyed by `label_key`/`description_key` and uses these only as a
    # fallback for a node type shipped before the messages caught up.
    label: str
    description: str
    label_key: str
    description_key: str
    output_ports: list[str]
    is_agent: bool
    agent_role: str | None = None
    agent_bindings: list[AgentBindingView] = Field(default_factory=list)
    dynamic_agent_binding: DynamicAgentBindingView | None = None
    config_schema: dict[str, Any]


class WorkflowTemplateView(ApiModel):
    id: str
    operation: str
    # `None` = the operation's generic graph. Only `text_to_image`/
    # `image_to_image` ever carry a value here — see `ImageAssetKind`.
    asset_kind: str | None = None
    version: int
    name: str
    graph: dict[str, Any]
    is_active: bool
    created_by_user_id: str | None = None
    reason: str | None = None
    created_at: dt.datetime


class WorkflowTemplatePublishRequest(DangerousAction):
    name: str = Field(min_length=1, max_length=120)
    graph: dict[str, Any]
    asset_kind: ImageAssetKind | None = None


class WorkflowTemplateValidateRequest(ApiModel):
    graph: dict[str, Any]
    # Needed to judge whether a bound agent declares this operation
    # among its capabilities. Optional so a caller that only wants the
    # structural checks can skip it.
    operation: Operation | None = None


class WorkflowTemplateValidateResponse(ApiModel):
    """`errors` block publishing; `warnings` only ask the operator to look."""

    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class WorkflowSandboxRunRequest(ApiModel):
    prompt: str = Field(min_length=1, max_length=2000)
    quality_tier: str = "standard"
    params: dict[str, Any] = Field(default_factory=dict)
    # The unpublished graph on the editor's canvas. Omitted means "run what
    # is live". Passing it is what makes the editor's edit -> run -> look
    # loop possible without publishing to production first; it is validated
    # exactly like a publish before it is executed, and stored on the job as
    # `graph_override_json` rather than becoming a template row.
    graph: dict[str, Any] | None = None


class WorkflowSandboxRunResult(ApiModel):
    job_id: str


class WorkflowSandboxRunSummary(ApiModel):
    """One past product-sandbox try-it, for the workflow editor's history.

    Detail (events, signed preview) stays on `GET /v1/admin/jobs/{id}` so
    this list never hits object storage per row.
    """

    job_id: str
    status: JobStatus
    quality_tier: str
    prompt_excerpt: str
    used_draft: bool
    user_display_name: str | None = None
    user_handle: str | None = None
    quoted_credits: int
    failure_code: str | None = None
    created_at: dt.datetime
    finished_at: dt.datetime | None = None
