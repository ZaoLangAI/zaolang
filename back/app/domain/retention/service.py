"""Age-based purges for tables that only ever grow.

Each function deletes in bounded batches rather than one `DELETE ... WHERE`
statement: these tables are actively written by live traffic (a new
`JobEvent` every SSE tick, a new `IdempotencyRecord` on every write endpoint),
and a single multi-million-row delete would hold locks and bloat the
transaction log for the whole sweep instead of making steady, interruptible
progress.
"""

from __future__ import annotations

import datetime as dt
import logging

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import GenerationJob, IdempotencyRecord, JobEvent, SystemLog, WebhookEvent
from app.models.base import utcnow
from app.models.enums import TERMINAL_JOB_STATUSES

logger = logging.getLogger(__name__)

# A client's own retry window is minutes, not days — this only needs to
# outlive the longest plausible double-click/retry, not become a second
# request log.
IDEMPOTENCY_RETENTION_DAYS = 14
# Long enough to investigate a billing dispute against the original inbound
# payload; short enough that `payload_json` does not accumulate forever.
WEBHOOK_EVENT_RETENTION_DAYS = 90
# Matches `WEBHOOK_EVENT_RETENTION_DAYS` — both are "recent operational
# history", not the audit trail (`AuditLog` is kept indefinitely).
SYSTEM_LOG_RETENTION_DAYS = 90
# SSE reconnection only ever needs a finished job's *own* history, and no
# product surface links back to a job's blow-by-blow event trace once it is
# long since terminal.
JOB_EVENT_RETENTION_DAYS = 90

_BATCH_SIZE = 5000


def purge_idempotency_records(
    session: Session, *, older_than_days: int = IDEMPOTENCY_RETENTION_DAYS
) -> int:
    cutoff = utcnow() - dt.timedelta(days=older_than_days)
    return _delete_in_batches(
        session,
        IdempotencyRecord,
        select(IdempotencyRecord.id).where(IdempotencyRecord.created_at < cutoff),
    )


def purge_webhook_events(
    session: Session, *, older_than_days: int = WEBHOOK_EVENT_RETENTION_DAYS
) -> int:
    """Only a processed event is eligible — an unprocessed one is still
    evidence `reconcile_webhooks` has not caught up to it yet."""
    cutoff = utcnow() - dt.timedelta(days=older_than_days)
    return _delete_in_batches(
        session,
        WebhookEvent,
        select(WebhookEvent.id).where(
            WebhookEvent.processed_at.is_not(None), WebhookEvent.processed_at < cutoff
        ),
    )


def purge_system_logs(session: Session, *, older_than_days: int = SYSTEM_LOG_RETENTION_DAYS) -> int:
    """`updated_at`, not `created_at`: a row is "last seen in this dedup
    window" (`TimestampMixin`'s `onupdate`), which is the signal an operator
    actually cares about — a burst that is still recurring must not be
    purged just because the window it first appeared in is old."""
    cutoff = utcnow() - dt.timedelta(days=older_than_days)
    return _delete_in_batches(
        session, SystemLog, select(SystemLog.id).where(SystemLog.updated_at < cutoff)
    )


def purge_job_events(session: Session, *, older_than_days: int = JOB_EVENT_RETENTION_DAYS) -> int:
    """Only events belonging to a job that is both terminal and old are
    eligible — a job still in flight needs its full history for SSE
    reconnection to replay from `Last-Event-ID`."""
    cutoff = utcnow() - dt.timedelta(days=older_than_days)
    terminal_job_ids = select(GenerationJob.id).where(
        GenerationJob.status.in_([status.value for status in TERMINAL_JOB_STATUSES]),
        GenerationJob.updated_at < cutoff,
    )
    return _delete_in_batches(
        session, JobEvent, select(JobEvent.id).where(JobEvent.job_id.in_(terminal_job_ids))
    )


def _delete_in_batches(session: Session, model: type, id_query) -> int:
    deleted_total = 0
    while True:
        batch_ids = session.scalars(id_query.limit(_BATCH_SIZE)).all()
        if not batch_ids:
            break
        session.execute(delete(model).where(model.id.in_(batch_ids)))
        session.commit()
        deleted_total += len(batch_ids)
        if len(batch_ids) < _BATCH_SIZE:
            break
    return deleted_total
