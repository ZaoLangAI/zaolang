"""Back-office payloads.

Console responses are deliberately wider than consumer ones: an operator needs
internal codes and raw state that must never leak to a public endpoint.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from pydantic import Field

from app.api.schemas.common import ApiModel
from app.models.enums import JobStatus, ModerationStatus, UserStatus


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
    quoted_credits: int
    actual_credits: int | None = None
    attempt_count: int = 0
    failure_code: str | None = None
    created_at: dt.datetime
    finished_at: dt.datetime | None = None


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


class AdminJobDetail(AdminJobSummary):
    """Full replay material for one job."""

    params: dict[str, Any] = Field(default_factory=dict)
    routing_trace: list[dict[str, Any]] = Field(default_factory=list)
    events: list[JobEventView] = Field(default_factory=list)
    attempts: list[ProviderAttemptView] = Field(default_factory=list)
    agent_runs: list[dict[str, Any]] = Field(default_factory=list)


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


class AgentRunView(ApiModel):
    id: str
    agent_name: str
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
