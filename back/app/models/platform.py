"""Moderation, reports, notifications, config centre, audit and ops records."""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import (
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
from app.models.enums import (
    DataRequestStatus,
    DataRequestType,
    ModerationStatus,
    ReportStatus,
)


class ModerationResult(Base):
    """Append-only safety verdict.

    A `REJECTED` row at any stage is final: no later agent or route may
    overturn it. Only a human reviewer can add a new row that supersedes it,
    and the original stays on the record.
    """

    __tablename__ = "moderation_results"

    id: Mapped[str] = id_column("mod")
    stage: Mapped[str] = mapped_column(String(32), nullable=False)
    subject_type: Mapped[str] = mapped_column(String(32), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    categories_json: Mapped[dict[str, Any]] = mapped_column(default=dict, nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    public_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_by: Mapped[str] = mapped_column(String(32), default="agent", nullable=False)
    reviewer_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    agent_run_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_moderation_results_subject", "subject_type", "subject_id"),
        Index("ix_moderation_results_status_created", "status", "created_at"),
    )


class ReportCase(Base, TimestampMixin):
    __tablename__ = "report_cases"

    id: Mapped[str] = id_column("rpt")
    reporter_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    subject_type: Mapped[str] = mapped_column(String(32), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(40), nullable=False)
    reason: Mapped[str] = mapped_column(String(32), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(24), default=ReportStatus.OPEN, nullable=False)
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    handled_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    handled_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_report_cases_status_created", "status", "created_at"),
        Index("ix_report_cases_subject", "subject_type", "subject_id"),
    )


class Notification(Base, TimestampMixin):
    __tablename__ = "notifications"

    id: Mapped[str] = id_column("ntf")
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    title_key: Mapped[str] = mapped_column(String(80), nullable=False)
    # Interpolation values for the i18n key, so notifications translate at read
    # time rather than being frozen in one language at write time.
    payload_json: Mapped[dict[str, Any]] = mapped_column(default=dict, nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    read_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_notifications_user_created", "user_id", "created_at"),)


class PlatformConfig(Base):
    """Versioned runtime configuration.

    Rows are append-only per key: editing writes a new version and marks it
    active, so history and one-click rollback come for free.
    """

    __tablename__ = "platform_configs"

    id: Mapped[str] = id_column("cfg")
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    value_json: Mapped[dict[str, Any]] = mapped_column(nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("key", "version", name="uq_platform_configs_key_version"),
        Index("ix_platform_configs_key_active", "key", "is_active"),
    )


class AuditLog(Base):
    """Append-only trail of every privileged action."""

    __tablename__ = "audit_logs"

    id: Mapped[str] = id_column("adt")
    actor_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    actor_roles: Mapped[str | None] = mapped_column(String(160), nullable=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # Summaries, not full rows: enough to audit, small enough to keep forever.
    before_json: Mapped[dict[str, Any]] = mapped_column(default=dict, nullable=False)
    after_json: Mapped[dict[str, Any]] = mapped_column(default=dict, nullable=False)
    # Required for high-risk actions; the API rejects the call without it.
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_audit_logs_created_at", "created_at"),
        Index("ix_audit_logs_actor", "actor_user_id"),
        Index("ix_audit_logs_target", "target_type", "target_id"),
        Index("ix_audit_logs_action", "action"),
    )


class IdempotencyRecord(Base):
    """Binds a key to the exact request that created it.

    Same key + same body replays the stored response; same key + different body
    is a conflict, which is how we detect a client reusing a key by mistake.
    """

    __tablename__ = "idempotency_records"

    id: Mapped[str] = id_column("idm")
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    endpoint: Mapped[str] = mapped_column(String(120), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response_status: Mapped[int] = mapped_column(Integer, nullable=False)
    response_snapshot: Mapped[dict[str, Any]] = mapped_column(nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "user_id", "endpoint", "idempotency_key", name="uq_idempotency_user_endpoint_key"
        ),
    )


class Announcement(Base, TimestampMixin):
    __tablename__ = "announcements"

    id: Mapped[str] = id_column("anc")
    kind: Mapped[str] = mapped_column(String(24), default="notice", nullable=False)
    title_zh: Mapped[str] = mapped_column(String(200), nullable=False)
    title_en: Mapped[str] = mapped_column(String(200), nullable=False)
    body_zh: Mapped[str] = mapped_column(Text, nullable=False)
    body_en: Mapped[str] = mapped_column(Text, nullable=False)
    starts_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_published: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class DataRequest(Base, TimestampMixin):
    """GDPR-style export or deletion request.

    Deletion anonymises the account but keeps lineage tombstones, so descendant
    provenance stays resolvable.
    """

    __tablename__ = "data_requests"

    id: Mapped[str] = id_column("drq")
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    type: Mapped[str] = mapped_column(String(24), default=DataRequestType.EXPORT, nullable=False)
    status: Mapped[str] = mapped_column(
        String(24), default=DataRequestStatus.PENDING, nullable=False
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_object_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    handled_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    handled_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_data_requests_status", "status"),)


class BackupRecord(Base, TimestampMixin):
    __tablename__ = "backup_records"

    id: Mapped[str] = id_column("bkp")
    kind: Mapped[str] = mapped_column(String(24), default="database", nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="running", nullable=False)
    object_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    triggered_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class ReconciliationReport(Base, TimestampMixin):
    """Snapshot of ledger health.

    `dangling_reserved_count` counts jobs whose reserve never settled — the
    direct line-of-sight check for "reserve must end in capture or release".
    """

    __tablename__ = "reconciliation_reports"

    id: Mapped[str] = id_column("rec")
    generated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    account_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    mismatched_account_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    dangling_reserved_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    details_json: Mapped[dict[str, Any]] = mapped_column(default=dict, nullable=False)


class ModerationQueueItem(Base, TimestampMixin):
    """Work item for the review console.

    Separate from `ModerationResult` because a verdict is a fact while a queue
    item is mutable state (claimed, resolved, reopened).
    """

    __tablename__ = "moderation_queue_items"

    id: Mapped[str] = id_column("mqi")
    subject_type: Mapped[str] = mapped_column(String(32), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(40), nullable=False)
    stage: Mapped[str] = mapped_column(String(32), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(
        String(24), default=ModerationStatus.PENDING, nullable=False
    )
    reason_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    claimed_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    resolved_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("subject_type", "subject_id", "stage", name="uq_moderation_queue_subject"),
        Index("ix_moderation_queue_status_priority", "status", "priority"),
    )
