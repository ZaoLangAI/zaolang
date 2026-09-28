"""Age-based purges for tables with no natural cap of their own.

Each test proves two things per table: a row past its retention window is
deleted, and a row that has not aged out yet — or is excluded by the
function's own eligibility rule (unprocessed webhook, non-terminal job) — is
left alone.
"""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.retention import service as retention
from app.models import GenerationJob, IdempotencyRecord, JobEvent, SystemLog, User, WebhookEvent
from app.models.base import new_id, utcnow
from app.models.enums import JobStatus
from tests.factories import make_job


def _old(days: int) -> dt.datetime:
    return utcnow() - dt.timedelta(days=days)


def test_purge_idempotency_records_only_deletes_rows_past_retention(
    db: Session, author: User
) -> None:
    fresh = IdempotencyRecord(
        user_id=author.id,
        endpoint="/v1/test",
        idempotency_key=new_id("idk"),
        request_hash="a" * 64,
        response_status=200,
        response_snapshot={},
        created_at=_old(1),
    )
    stale = IdempotencyRecord(
        user_id=author.id,
        endpoint="/v1/test",
        idempotency_key=new_id("idk"),
        request_hash="b" * 64,
        response_status=200,
        response_snapshot={},
        created_at=_old(retention.IDEMPOTENCY_RETENTION_DAYS + 1),
    )
    db.add_all([fresh, stale])
    db.flush()

    deleted = retention.purge_idempotency_records(db)

    assert deleted == 1
    remaining = set(db.scalars(select(IdempotencyRecord.id)))
    assert fresh.id in remaining
    assert stale.id not in remaining


def test_purge_webhook_events_only_deletes_processed_rows_past_retention(db: Session) -> None:
    cutoff_days = retention.WEBHOOK_EVENT_RETENTION_DAYS + 1
    processed_stale = WebhookEvent(
        provider="stripe",
        external_event_id=new_id("evt"),
        event_type="payment.succeeded",
        payload_json={},
        processed_at=_old(cutoff_days),
        created_at=_old(cutoff_days),
    )
    processed_fresh = WebhookEvent(
        provider="stripe",
        external_event_id=new_id("evt"),
        event_type="payment.succeeded",
        payload_json={},
        processed_at=_old(1),
        created_at=_old(1),
    )
    # An old but never-processed event is still evidence `reconcile_webhooks`
    # has not caught up — it must survive regardless of age.
    unprocessed_stale = WebhookEvent(
        provider="stripe",
        external_event_id=new_id("evt"),
        event_type="payment.succeeded",
        payload_json={},
        processed_at=None,
        created_at=_old(cutoff_days),
    )
    db.add_all([processed_stale, processed_fresh, unprocessed_stale])
    db.flush()

    deleted = retention.purge_webhook_events(db)

    assert deleted == 1
    remaining = set(db.scalars(select(WebhookEvent.id)))
    assert processed_stale.id not in remaining
    assert processed_fresh.id in remaining
    assert unprocessed_stale.id in remaining


def test_purge_system_logs_keys_off_updated_at_not_created_at(db: Session) -> None:
    """A row first created long ago but bumped by a recent recurrence of the
    same burst (`TimestampMixin.updated_at`'s `onupdate`) must not be purged
    just because it is old by `created_at`."""
    old_cutoff = retention.SYSTEM_LOG_RETENTION_DAYS + 1
    recurring = SystemLog(
        source="auth",
        event="test.recurring",
        level="warning",
        message="still happening",
        dedup_key=f"test:{new_id('t')}",
        window_started_at=_old(old_cutoff),
        created_at=_old(old_cutoff),
    )
    dormant = SystemLog(
        source="auth",
        event="test.dormant",
        level="warning",
        message="not seen in a while",
        dedup_key=f"test:{new_id('t')}",
        window_started_at=_old(old_cutoff),
        created_at=_old(old_cutoff),
    )
    db.add_all([recurring, dormant])
    db.flush()
    # `updated_at` has an `onupdate=func.now()`; only an actual UPDATE bumps
    # it, so simulate "seen again recently" the same way `system_log.emit`'s
    # bump path would.
    db.execute(
        SystemLog.__table__.update()
        .where(SystemLog.id == recurring.id)
        .values(occurrence_count=2, updated_at=utcnow())
    )
    db.execute(
        SystemLog.__table__.update()
        .where(SystemLog.id == dormant.id)
        .values(updated_at=_old(old_cutoff))
    )
    db.flush()

    deleted = retention.purge_system_logs(db)

    assert deleted == 1
    remaining = set(db.scalars(select(SystemLog.id)))
    assert recurring.id in remaining
    assert dormant.id not in remaining


def _event(job_id: str, sequence: int, *, created_at: dt.datetime) -> JobEvent:
    return JobEvent(
        job_id=job_id,
        sequence=sequence,
        event_type="progress",
        status=JobStatus.RUNNING,
        progress=50,
        public_message="test",
        created_at=created_at,
    )


def test_purge_job_events_only_touches_old_terminal_jobs(db: Session, author: User) -> None:
    cutoff_days = retention.JOB_EVENT_RETENTION_DAYS + 1

    terminal_and_old = make_job(db, author, status=JobStatus.SUCCEEDED)
    db.execute(
        GenerationJob.__table__.update()
        .where(GenerationJob.id == terminal_and_old.id)
        .values(updated_at=_old(cutoff_days))
    )
    db.add(_event(terminal_and_old.id, 1, created_at=_old(cutoff_days)))

    # Terminal, but settled recently — its history is still worth keeping for
    # a while (e.g. an admin investigating a just-closed job).
    terminal_but_recent = make_job(db, author, status=JobStatus.SUCCEEDED)
    db.add(_event(terminal_but_recent.id, 1, created_at=_old(cutoff_days)))

    # Old-looking event timestamp, but the job itself is still running — SSE
    # reconnection needs the full history to replay from `Last-Event-ID`.
    still_running = make_job(db, author, status=JobStatus.RUNNING)
    db.add(_event(still_running.id, 1, created_at=_old(cutoff_days)))

    db.flush()

    deleted = retention.purge_job_events(db)

    assert deleted == 1
    remaining_job_ids = set(db.scalars(select(JobEvent.job_id)))
    assert terminal_and_old.id not in remaining_job_ids
    assert terminal_but_recent.id in remaining_job_ids
    assert still_running.id in remaining_job_ids


def test_purge_expired_records_task_reports_a_count_per_table(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from contextlib import contextmanager

    from app.workers import tasks

    @contextmanager
    def _fake_scope():
        yield db

    monkeypatch.setattr(tasks, "session_scope", _fake_scope)

    result = tasks.purge_expired_records()

    assert set(result) == {
        "idempotency_records",
        "webhook_events",
        "system_logs",
        "job_events",
    }
    assert all(isinstance(v, int) for v in result.values())
