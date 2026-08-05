"""Workflows, generation jobs, job events, provider attempts and agent runs."""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, id_column
from app.models.enums import JobStatus, ProviderAttemptStatus, ProviderKind


class Workflow(Base, TimestampMixin):
    __tablename__ = "workflows"

    id: Mapped[str] = id_column("wfl")
    slug: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    operation: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="active", nullable=False)


class WorkflowVersion(Base, TimestampMixin):
    """A locked, reviewed workflow definition.

    `locked_definition_hash` is what makes "ComfyUI only runs approved
    workflows" enforceable: the executor refuses anything whose hash drifts.
    """

    __tablename__ = "workflow_versions"

    id: Mapped[str] = id_column("wfv")
    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False
    )
    semantic_version: Mapped[str] = mapped_column(String(32), nullable=False)
    capability_json: Mapped[dict[str, Any]] = mapped_column(nullable=False)
    parameter_schema_json: Mapped[dict[str, Any]] = mapped_column(nullable=False)
    locked_definition_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    is_approved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        UniqueConstraint("workflow_id", "semantic_version", name="uq_workflow_versions_semver"),
    )


class GenerationJob(Base, TimestampMixin):
    __tablename__ = "generation_jobs"

    id: Mapped[str] = id_column("job")
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    draft_id: Mapped[str | None] = mapped_column(
        ForeignKey("drafts.id", ondelete="SET NULL"), nullable=True
    )
    source_work_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("work_versions.id", ondelete="RESTRICT"), nullable=True
    )
    operation: Mapped[str] = mapped_column(String(32), nullable=False)
    request_json: Mapped[dict[str, Any]] = mapped_column(nullable=False)
    quality_tier: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default=JobStatus.CREATED, nullable=False)

    quoted_credits: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reserved_credits: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    actual_credits: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_credits: Mapped[int | None] = mapped_column(Integer, nullable=True)

    idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False)
    selected_route_summary_json: Mapped[dict[str, Any]] = mapped_column(
        default=dict, nullable=False
    )
    # Every candidate considered plus why it was filtered or chosen. Replayed in
    # the ops console; required by the "record each filter reason" rule.
    routing_trace_json: Mapped[list[Any]] = mapped_column(default=list, nullable=False)
    output_asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("assets.id", ondelete="SET NULL"), nullable=True
    )
    output_work_version_id: Mapped[str | None] = mapped_column(String(40), nullable=True)

    estimated_seconds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    failure_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancel_requested_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    started_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retry_of_job_id: Mapped[str | None] = mapped_column(String(40), nullable=True)

    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key", name="uq_generation_jobs_idempotency"),
        Index("ix_generation_jobs_user_id_status", "user_id", "status"),
        Index("ix_generation_jobs_status_created_at", "status", "created_at"),
    )


class JobEvent(Base):
    """Append-only progress log. SSE clients resume from `sequence` via
    `Last-Event-ID`, so sequences must be gapless per job."""

    __tablename__ = "job_events"

    id: Mapped[str] = id_column("evt")
    job_id: Mapped[str] = mapped_column(
        ForeignKey("generation_jobs.id", ondelete="CASCADE"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Written for the end user; must never contain provider names or stack traces.
    public_message: Mapped[str] = mapped_column(Text, nullable=False)
    # Searchable code for support; safe to show alongside the friendly message.
    internal_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(default=dict, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("job_id", "sequence", name="uq_job_events_job_sequence"),
        Index("ix_job_events_job_id_sequence", "job_id", "sequence"),
    )


class ProviderAttempt(Base):
    __tablename__ = "provider_attempts"

    id: Mapped[str] = id_column("atp")
    job_id: Mapped[str] = mapped_column(
        ForeignKey("generation_jobs.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_kind: Mapped[str] = mapped_column(
        String(32), default=ProviderKind.OPEN_WORKFLOW, nullable=False
    )
    model_or_workflow_version: Mapped[str] = mapped_column(String(120), nullable=False)
    external_task_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(24), default=ProviderAttemptStatus.SUBMITTED, nullable=False
    )
    cost_minor: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Redacted before persistence: no keys, no signed URLs, no payment data.
    raw_metadata_redacted_json: Mapped[dict[str, Any]] = mapped_column(default=dict, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("job_id", "attempt_number", name="uq_provider_attempts_job_attempt"),
        Index("ix_provider_attempts_provider_status", "provider", "status"),
    )


class ProviderStat(Base, TimestampMixin):
    """Rolling success/latency/cost aggregates that feed the router score.

    Kept as a table rather than computed on the fly so routing stays fast and
    so the ops console can show exactly what the router saw.
    """

    __tablename__ = "provider_stats"

    id: Mapped[str] = id_column("pst")
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    operation: Mapped[str] = mapped_column(String(32), nullable=False)
    quality_tier: Mapped[str] = mapped_column(String(24), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    successes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_latency_ms: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    total_cost_minor: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "provider", "operation", "quality_tier", name="uq_provider_stats_dimension"
        ),
    )


class AgentRun(Base):
    """One agent invocation. Records the model actually used, token spend and
    whether the call degraded to the deterministic stub."""

    __tablename__ = "agent_runs"

    id: Mapped[str] = id_column("agr")
    job_id: Mapped[str | None] = mapped_column(
        ForeignKey("generation_jobs.id", ondelete="CASCADE"), nullable=True
    )
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    agent_name: Mapped[str] = mapped_column(String(32), nullable=False)
    mode: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    degraded: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    degrade_reason: Mapped[str | None] = mapped_column(String(160), nullable=True)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Which `llm_providers` config entry actually served this call, or the
    # literal "legacy" when the failover pool was empty. Not a foreign key:
    # endpoints are config entries, not rows, and can be renamed or removed.
    endpoint_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    output_json: Mapped[dict[str, Any]] = mapped_column(default=dict, nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_agent_runs_job_id", "job_id"),
        Index("ix_agent_runs_agent_name_created_at", "agent_name", "created_at"),
    )
