"""Operational security signal, distinct from `AuditLog`.

`AuditLog` is a before/after record of a privileged actor's deliberate write.
`SystemLog` is the opposite shape: high-frequency, often-anonymous runtime
events (a failed login, a rate limit trip, a permission denial) that are only
worth keeping in aggregate. `occurrence_count` is what makes that affordable —
a burst within one `window_seconds` bucket collapses into a single row that
gets its count bumped instead of one row per event.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import DateTime, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, id_column


class SystemLog(Base, TimestampMixin):
    """One row per `(source, event, dedup_key, window_started_at)`.

    `updated_at` (from `TimestampMixin`) doubles as "last seen in this window";
    `created_at` is "first seen in this window".
    """

    __tablename__ = "system_logs"

    id: Mapped[str] = id_column("slg")
    source: Mapped[str] = mapped_column(String(24), nullable=False)
    event: Mapped[str] = mapped_column(String(64), nullable=False)
    level: Mapped[str] = mapped_column(String(16), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    # Groups occurrences that should collapse together, e.g. `ip:1.2.3.4` for a
    # login-failure burst from one address.
    dedup_key: Mapped[str] = mapped_column(String(160), nullable=False)
    window_started_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    occurrence_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    user_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Already-redacted context (rule bucket, rejected role, etc.); never a
    # password or token.
    details_json: Mapped[dict[str, Any]] = mapped_column(default=dict, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "source", "event", "dedup_key", "window_started_at", name="uq_system_logs_window"
        ),
        Index("ix_system_logs_created_at", "created_at"),
        Index("ix_system_logs_source_event", "source", "event"),
    )
