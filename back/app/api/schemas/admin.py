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
    JobStatus,
    LearnPostStatus,
    ModerationStatus,
    Operation,
    RedemptionCodeKind,
    UserStatus,
)


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
    llm_mode: str
    llm_reachable: bool | None = None
    app_version: str
    generated_at: dt.datetime


class AdminJobSummary(ApiModel):
    id: str
    user_id: str
    status: JobStatus
    operation: str
    quality_tier: str
    provider: str | None = None
    routing_reason: str | None = None
    quoted_credits: int
    actual_credits: int | None = None
    attempt_count: int = 0
    failure_code: str | None = None
    created_at: dt.datetime
    finished_at: dt.datetime | None = None


class JobStatsView(ApiModel):
    """Aggregate job throughput for the statistics hub — not one job's detail."""

    generated_at: dt.datetime
    window_hours: int
    by_status: dict[str, int] = Field(default_factory=dict)
    by_operation: dict[str, int] = Field(default_factory=dict)
    total_jobs: int = 0
    avg_completion_ms: float | None = None


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
    created_at: dt.datetime


class AgentRunView(ApiModel):
    id: str
    agent_name: str
    # Which agent and prompt slot served this call. Null for runs recorded
    # before agent profiles existed.
    agent_profile_id: str | None = None
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
    created_at: dt.datetime


class AdminJobDetail(AdminJobSummary):
    """Full replay material for one job."""

    params: dict[str, Any] = Field(default_factory=dict)
    routing_trace: list[dict[str, Any]] = Field(default_factory=list)
    events: list[JobEventView] = Field(default_factory=list)
    attempts: list[ProviderAttemptView] = Field(default_factory=list)
    agent_runs: list[AgentRunView] = Field(default_factory=list)


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
    effective_cost: int
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
    public_message: str | None = None
    created_at: dt.datetime


class ModerationWorkDetailView(ApiModel):
    id: str
    title: str
    description: str | None = None
    prompt: str | None = None
    cover_url: str | None = None
    media_url: str | None = None
    owner_user_id: str
    visibility: str
    lifecycle_status: str
    tombstone_reason: str | None = None
    created_at: dt.datetime


class ModerationSubjectDetailView(ApiModel):
    """Full context for one queue item: the current decision plus everything
    that led to it, so a reviewer can judge a REJECTED/HIDDEN call without
    trusting the summary row alone."""

    queue_item: ModerationQueueView
    history: list[ModerationHistoryEntry]
    work: ModerationWorkDetailView | None = None
    skill: CreationSkillAdminView | None = None


class ReportCaseView(ApiModel):
    id: str
    reporter_user_id: str | None = None
    subject_type: str
    subject_id: str
    reason: str
    detail: str | None = None
    status: str
    created_at: dt.datetime


class ReportResolveRequest(ApiModel):
    status: Literal["resolved", "rejected", "escalated"]
    resolution_note: str = Field(min_length=1, max_length=1000)


class TombstoneRequest(DangerousAction):
    pass


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


class CreationSkillAdminView(ApiModel):
    id: str
    owner_user_id: str
    title: str
    description: str
    category: CreationSkillCategory
    cover_url: str | None = None
    visibility: CreationSkillVisibility
    status: CreationSkillStatus
    usage_count: int
    reject_reason: str | None = None
    created_at: dt.datetime


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
    note: str | None = Field(default=None, max_length=300)


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


class LlmProviderEndpointView(ApiModel):
    """Read model for one model-provider endpoint.

    `api_key` itself never appears here — only whether one is set and a
    truncated preview — so a GET response is always safe to render or log.

    `role`/`backup_order` are endpoint-level for both `general` and `media`.
    For media, `capabilities` is derived and read-only: it lists which tags
    the declared `model` + `input_modalities`/`output_modalities` cover.
    """

    id: str
    name: str
    base_url: str
    api_key_configured: bool
    api_key_preview: str | None = None
    kind: Literal["general", "media"] = "general"
    models: list[str] = Field(default_factory=list)
    # `kind="media"` only.
    model: str = ""
    input_modalities: list[str] = Field(default_factory=list)
    output_modalities: list[str] = Field(default_factory=list)
    # Derived from the modalities above; read-only.
    capabilities: list[str] = Field(default_factory=list)
    max_concurrency: int
    role: Literal["primary", "backup"]
    backup_order: int
    timeout_ms: int
    enabled: bool
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


class LlmProviderEndpointUpsertRequest(ApiModel):
    name: str = Field(min_length=1, max_length=100)
    base_url: str = Field(min_length=1, max_length=500)
    # None keeps the stored key unchanged; "" clears it; anything else replaces it.
    api_key: str | None = None
    kind: Literal["general", "media"] = "general"
    # `kind="general"` only.
    models: list[str] = Field(default_factory=list)
    role: Literal["primary", "backup"] = "backup"
    backup_order: int = Field(default=100, ge=1, le=1000)
    # `kind="media"` only: one model id plus the modalities it supports.
    # Capability tags are derived server-side, not submitted here.
    model: str = Field(default="", max_length=200)
    input_modalities: list[str] = Field(default_factory=list)
    output_modalities: list[str] = Field(default_factory=list)
    max_concurrency: int = Field(default=4, ge=1, le=256)
    timeout_ms: int = Field(default=30_000, ge=1_000, le=120_000)
    enabled: bool = True


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
    execute. `category` drives which half of the create form applies —
    `judgment` binds one LLM model, `creative` binds media endpoints with a
    cost weight each — and `operations` is what the media-candidate picker
    filters by.
    """

    role: str
    display_name: str
    category: Literal["judgment", "creative"]
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
    category: Literal["judgment", "creative"] = "judgment"
    enabled: bool
    sort_order: int
    candidate_endpoint_ids: list[str] = Field(default_factory=list)
    prompt_slots: list[PromptSlotView] = Field(default_factory=list)


class MediaCandidate(ApiModel):
    """One media route a creative agent may use, with a cost preference.

    `weight` is shown to the routing agent as operational context alongside
    each candidate's observed success rate, latency and cost — it is not a
    coefficient. Nothing in `app/agents/router.py` ranks by it; the routing
    agent still makes the call.
    """

    endpoint_id: str = Field(min_length=1, max_length=64)
    # A capability tag the endpoint derives from its modalities, e.g.
    # `text_to_video`. Together with `endpoint_id` this is the router's
    # catalogue key (`"{endpoint_id}:{capability}"`).
    capability: str = Field(min_length=1, max_length=40)
    weight: int = Field(default=100, ge=1, le=1_000)


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
    category: Literal["judgment", "creative"] = "judgment"
    operations: list[str] = Field(default_factory=list)
    is_default: bool
    enabled: bool
    # `judgment` agents only. Null means the agent draws from the shared
    # `kind="general"` pool, which is what every agent did before per-agent
    # bindings existed.
    default_endpoint_id: str | None = None
    backup_endpoint_id: str | None = None
    max_tokens: int | None = None
    temperature: float | None = None
    reasoning_model: bool | None = None
    # `creative` agents only.
    media_candidates: list[MediaCandidate] = Field(default_factory=list)
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
    max_tokens: int | None = Field(default=None, ge=0, le=32_768)
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    reasoning_model: bool | None = None
    media_candidates: list[MediaCandidate] = Field(default_factory=list)


class AgentProfileUpdateRequest(ApiModel):
    """Every field is optional and `None` means "leave as is".

    An **empty string** on either endpoint id is how the console clears a
    model pin, and an **empty list** clears media candidates — otherwise an
    agent could never go back to the shared pool once pinned.
    """

    display_name: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=2_000)
    operations: list[str] | None = None
    is_default: bool | None = None
    enabled: bool | None = None
    default_endpoint_id: str | None = Field(default=None, max_length=64)
    backup_endpoint_id: str | None = Field(default=None, max_length=64)
    max_tokens: int | None = Field(default=None, ge=0, le=32_768)
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    reasoning_model: bool | None = None
    media_candidates: list[MediaCandidate] | None = None


class SkillTemplateView(ApiModel):
    """A starting prompt the skill editor can load.

    Loading one only fills the form: publishing stays a separate confirmed
    action, because the published text is what decides whether content gets
    rejected or a retry spends credits.
    """

    key: str
    label: str
    description: str = ""
    category: Literal["judgment", "creative"]
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


class NodeTypeView(ApiModel):
    """One entry in the admin-facing node palette.

    `config_schema` is the node type's Pydantic config model rendered as a
    JSON Schema, so the editor can generate its property-panel form without a
    hand-maintained mirror of `app.workflows.configs`.
    """

    type: str
    category: str
    label: str
    description: str
    output_ports: list[str]
    is_agent: bool
    agent_role: str | None = None
    agent_bindings: list[AgentBindingView] = Field(default_factory=list)
    config_schema: dict[str, Any]


class WorkflowTemplateView(ApiModel):
    id: str
    operation: str
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


class WorkflowDryRunRequest(ApiModel):
    prompt: str = Field(min_length=1, max_length=2000)
    quality_tier: str = "standard"
    params: dict[str, Any] = Field(default_factory=dict)


class WorkflowDryRunStepView(ApiModel):
    node_id: str
    node_type: str
    port: str
    agent_run_id: str | None = None


class WorkflowDryRunResult(ApiModel):
    status: JobStatus
    failure_code: str | None = None
    asset_id: str | None = None
    trace: list[WorkflowDryRunStepView] = Field(default_factory=list)
