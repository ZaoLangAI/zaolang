"""Audit trail.

Every privileged write records who did what, to which object, with what
before/after summary and — for high-risk actions — a written reason. Rows are
never updated or deleted; a correction is a new row.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from fastapi import Request
from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.api.request_utils import client_ip
from app.domain.errors import ReasonRequired
from app.models import AuditLog, User
from app.models.base import utcnow
from app.observability.context import get_request_id
from app.observability.logging import redact

# These cannot be performed without an operator explaining why.
REASON_REQUIRED_ACTIONS = frozenset(
    {
        "credit.adjust",
        "work.tombstone",
        "work.hide",
        "user.suspend",
        "user.unsuspend",
        "user.grant_role",
        "config.rollback",
        "job.force_terminate",
        "agent.rebind_model",
        "data.restore",
        "data.reset",
        "data_request.approve_deletion",
    }
)


def record(
    session: Session,
    *,
    actor: User | None,
    action: str,
    target_type: str,
    target_id: str | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    reason: str | None = None,
    request: Request | None = None,
) -> AuditLog:
    if action in REASON_REQUIRED_ACTIONS and not (reason or "").strip():
        raise ReasonRequired()

    entry = AuditLog(
        actor_user_id=actor.id if actor else None,
        actor_roles=",".join(actor.roles) if actor else None,
        action=action,
        target_type=target_type,
        target_id=target_id,
        # Secrets can appear in a config diff, so both sides are redacted before
        # they reach a row an operator can read back.
        before_json=redact(before or {}),
        after_json=redact(after or {}),
        reason=(reason or "").strip() or None,
        request_id=get_request_id(),
        ip_address=client_ip(request),
        user_agent=(request.headers.get("user-agent", "")[:255] if request else None),
        created_at=utcnow(),
    )
    session.add(entry)
    session.flush()
    return entry


def search(
    session: Session,
    *,
    actor_user_id: str | None = None,
    action: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    since: dt.datetime | None = None,
    until: dt.datetime | None = None,
    before: dt.datetime | None = None,
    cursor: str | None = None,
    limit: int = 50,
) -> list[AuditLog]:
    stmt: Select[tuple[AuditLog]] = select(AuditLog).order_by(
        AuditLog.created_at.desc(), AuditLog.id.desc()
    )
    if actor_user_id:
        stmt = stmt.where(AuditLog.actor_user_id == actor_user_id)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if target_type:
        stmt = stmt.where(AuditLog.target_type == target_type)
    if target_id:
        stmt = stmt.where(AuditLog.target_id == target_id)
    if since:
        stmt = stmt.where(AuditLog.created_at >= since)
    if until:
        stmt = stmt.where(AuditLog.created_at <= until)
    if before:
        stmt = stmt.where(AuditLog.created_at < before)
    if cursor:
        stmt = stmt.where(AuditLog.id < cursor)
    return list(session.scalars(stmt.limit(limit)))
