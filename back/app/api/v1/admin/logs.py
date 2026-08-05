"""Unified log centre: merges privileged audit rows with runtime system signals."""

from __future__ import annotations

import datetime as dt
from typing import Any

from fastapi import APIRouter, Query

from app.api.deps import DbSession
from app.api.request_utils import as_utc
from app.api.schemas.admin import LogEntryView
from app.api.schemas.common import Page
from app.api.v1.admin.deps import AdminRead, Viewer
from app.domain.audit import service as audit
from app.domain.system_log import service as system_log
from app.models import AuditLog, SystemLog
from app.models.enums import SystemLogSource

router = APIRouter(tags=["admin:logs"])

AUDIT_SOURCE = "audit"
SYSTEM_SOURCES = frozenset(s.value for s in SystemLogSource)
# When merging two tables, over-fetch so interleaved rows still fill one page.
_MERGE_OVERFETCH = 50


@router.get("/logs", response_model=Page[LogEntryView])
def list_logs(
    session: DbSession,
    user: Viewer,
    _: AdminRead,
    source: str | None = None,
    level: str | None = None,
    actor_user_id: str | None = None,
    q: str | None = None,
    created_after: dt.datetime | None = None,
    created_before: dt.datetime | None = None,
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> Page[LogEntryView]:
    after = as_utc(created_after) if created_after else None
    cursor_dt = _parse_cursor(cursor)
    until = None if cursor_dt else (as_utc(created_before) if created_before else None)
    before = cursor_dt
    fetch = limit + (_MERGE_OVERFETCH if _merging(source) else 1)

    entries: list[LogEntryView] = []
    if source is None or source == AUDIT_SOURCE:
        audit_rows = audit.search(
            session,
            actor_user_id=actor_user_id,
            since=after,
            until=until,
            before=before,
            limit=fetch,
        )
        entries.extend(_from_audit(row) for row in audit_rows)

    if source is None or source in SYSTEM_SOURCES:
        sys_source = SystemLogSource(source) if source in SYSTEM_SOURCES else None
        system_rows = system_log.search(
            session,
            source=sys_source,
            user_id=actor_user_id,
            level=level,
            q=q,
            since=after,
            until=until,
            before=before,
            limit=fetch,
        )
        entries.extend(_from_system(row) for row in system_rows)

    if q and (source is None or source == AUDIT_SOURCE):
        needle = q.casefold()
        entries = [
            entry
            for entry in entries
            if needle in entry.event.casefold() or needle in entry.message.casefold()
        ]
    if level and (source is None or source == AUDIT_SOURCE):
        entries = [entry for entry in entries if entry.level == level]

    entries.sort(key=lambda entry: (entry.occurred_at, entry.id), reverse=True)
    has_more = len(entries) > limit
    page = entries[:limit]
    return Page(
        items=page,
        next_cursor=page[-1].occurred_at.isoformat() if has_more and page else None,
        has_more=has_more,
    )


def _merging(source: str | None) -> bool:
    return source is None


def _parse_cursor(raw: str | None) -> dt.datetime | None:
    if not raw:
        return None
    try:
        parsed = dt.datetime.fromisoformat(raw)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.UTC)


def _from_audit(row: AuditLog) -> LogEntryView:
    target = f"{row.target_type}/{row.target_id or '—'}"
    details: dict[str, Any] = {}
    if row.before_json:
        details["before"] = row.before_json
    if row.after_json:
        details["after"] = row.after_json
    if row.actor_roles:
        details["actor_roles"] = row.actor_roles
    if row.user_agent:
        details["user_agent"] = row.user_agent
    return LogEntryView(
        id=row.id,
        source=AUDIT_SOURCE,
        level="info",
        event=row.action,
        message=f"{row.action} → {target}",
        actor_user_id=row.actor_user_id,
        target=target,
        ip_address=row.ip_address,
        request_id=row.request_id,
        reason=row.reason,
        details=details,
        occurred_at=row.created_at,
    )


def _from_system(row: SystemLog) -> LogEntryView:
    details = dict(row.details_json)
    if row.path:
        details["path"] = row.path
    details["dedup_key"] = row.dedup_key
    return LogEntryView(
        id=row.id,
        source=row.source,
        level=row.level,
        event=row.event,
        message=row.message,
        actor_user_id=row.user_id,
        target=row.path,
        ip_address=row.ip_address,
        request_id=row.request_id,
        occurrence_count=row.occurrence_count,
        details=details,
        occurred_at=row.updated_at,
    )
