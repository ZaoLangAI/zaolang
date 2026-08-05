"""Emits a `SystemLog` row, collapsing a burst of the same event into one row
per time window instead of one row per occurrence.

Redis owns the burst — an atomic `INCR` decides, for every caller racing on
the same `(source, event, dedup_key, window)`, exactly one of them that it is
"first" — and Postgres only ever sees an INSERT for that first occurrence
plus a periodic count bump for the rest. `emit()` always commits through its
own connection rather than the caller's session: the two headline callers
(a failed login, a dependency raising `Forbidden`) are about to reject the
request without committing anything, so borrowing that session would lose
the very row this module exists to keep.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any

import redis
from fastapi import Request
from sqlalchemy import Select, select, update
from sqlalchemy.orm import Session

from app.api.rate_limit import get_redis
from app.api.request_utils import client_ip
from app.db import session_scope
from app.models import SystemLog
from app.models.enums import SystemLogLevel, SystemLogSource
from app.observability.context import get_request_id

logger = logging.getLogger(__name__)

DEFAULT_WINDOW_SECONDS = 60
# Diagnostic count, not a ledger: once the row exists, refresh it only every
# Nth occurrence rather than on every single one.
_COUNT_REFRESH_STRIDE = 10
_DEDUP_KEY_MAX_LEN = 160


def emit(
    *,
    source: SystemLogSource,
    event: str,
    message: str,
    dedup_key: str,
    level: SystemLogLevel = SystemLogLevel.WARNING,
    window_seconds: int = DEFAULT_WINDOW_SECONDS,
    user_id: str | None = None,
    request: Request | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Best-effort: swallows Redis and DB failures rather than letting an
    observability write ever fail the request that triggered it."""
    dedup_key = dedup_key[:_DEDUP_KEY_MAX_LEN]
    window_seconds = max(window_seconds, 1)
    now = dt.datetime.now(dt.UTC)
    window_epoch = int(now.timestamp()) // window_seconds
    redis_key = f"slog:{source}:{event}:{dedup_key}:{window_epoch}"

    try:
        pipe = get_redis().pipeline()
        pipe.incr(redis_key)
        pipe.expire(redis_key, window_seconds + 5)
        count, _ = pipe.execute()
    except redis.RedisError:
        logger.warning("system_log: redis unavailable, dropping %s.%s", source, event)
        return

    if count > 1 and count % _COUNT_REFRESH_STRIDE != 0:
        return

    window_started_at = dt.datetime.fromtimestamp(window_epoch * window_seconds, dt.UTC)
    try:
        with session_scope() as session:
            if count == 1:
                session.add(
                    SystemLog(
                        source=source.value,
                        event=event,
                        level=level.value,
                        message=message[:2000],
                        dedup_key=dedup_key,
                        window_started_at=window_started_at,
                        occurrence_count=1,
                        user_id=user_id,
                        ip_address=client_ip(request),
                        path=request.url.path if request else None,
                        request_id=get_request_id() or None,
                        details_json=details or {},
                    )
                )
            else:
                session.execute(
                    update(SystemLog)
                    .where(
                        SystemLog.source == source.value,
                        SystemLog.event == event,
                        SystemLog.dedup_key == dedup_key,
                        SystemLog.window_started_at == window_started_at,
                    )
                    .values(occurrence_count=count)
                )
    except Exception:
        logger.exception("system_log: failed to persist %s.%s", source, event)


def search(
    session: Session,
    *,
    source: SystemLogSource | None = None,
    user_id: str | None = None,
    level: str | None = None,
    q: str | None = None,
    since: dt.datetime | None = None,
    until: dt.datetime | None = None,
    before: dt.datetime | None = None,
    limit: int = 50,
) -> list[SystemLog]:
    """Ordered by `updated_at`: a window that just recurred is more relevant to
    an operator scanning the feed than one that only fired once an hour ago."""
    stmt: Select[tuple[SystemLog]] = select(SystemLog).order_by(
        SystemLog.updated_at.desc(), SystemLog.id.desc()
    )
    if source:
        stmt = stmt.where(SystemLog.source == source.value)
    if user_id:
        stmt = stmt.where(SystemLog.user_id == user_id)
    if level:
        stmt = stmt.where(SystemLog.level == level)
    if q:
        needle = f"%{q}%"
        stmt = stmt.where(
            SystemLog.event.ilike(needle) | SystemLog.message.ilike(needle)
        )
    if since:
        stmt = stmt.where(SystemLog.updated_at >= since)
    if until:
        stmt = stmt.where(SystemLog.updated_at <= until)
    if before:
        stmt = stmt.where(SystemLog.updated_at < before)
    return list(session.scalars(stmt.limit(limit)))
