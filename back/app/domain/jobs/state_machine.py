"""Generation job state transitions.

Transitions are conditional UPDATEs with the allowed source states in the WHERE
clause. Two workers racing to finish the same job therefore produce exactly one
winner, and a terminal job can never be reopened by a late provider callback.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.db import rows_affected
from app.domain.errors import InvalidJobTransition, JobNotCancellable, NotFound
from app.models import GenerationJob, JobEvent
from app.models.base import utcnow
from app.models.enums import (
    CANCELLABLE_JOB_STATUSES,
    JOB_TRANSITIONS,
    JobEventType,
    JobStatus,
)


def transition(
    session: Session,
    job_id: str,
    target: JobStatus,
    *,
    failure_code: str | None = None,
    failure_message: str | None = None,
    actual_credits: int | None = None,
    output_asset_id: str | None = None,
    now: dt.datetime | None = None,
) -> GenerationJob:
    """Moves a job to `target`, or raises if the move is illegal.

    Only statuses that legally precede `target` are accepted by the UPDATE, so
    the check and the write cannot drift apart under concurrency.
    """
    sources = [s for s, allowed in JOB_TRANSITIONS.items() if target in allowed]
    if not sources:
        raise InvalidJobTransition(f"没有任何状态可以迁移到 {target}。")

    moment = now or utcnow()
    values: dict[str, object] = {"status": target}
    if target in (JobStatus.SUBMITTED, JobStatus.RUNNING):
        # First entry into execution wins; a submitted→running move must not
        # reset the clock the user already sees.
        values["started_at"] = func.coalesce(GenerationJob.started_at, moment)
    if JobStatus(target).is_terminal:
        values["finished_at"] = moment
    if failure_code is not None:
        values["failure_code"] = failure_code
    if failure_message is not None:
        values["failure_message"] = failure_message
    if actual_credits is not None:
        values["actual_credits"] = actual_credits
    if output_asset_id is not None:
        values["output_asset_id"] = output_asset_id

    matched = rows_affected(
        session,
        update(GenerationJob)
        .where(
            GenerationJob.id == job_id,
            GenerationJob.status.in_([s.value for s in sources]),
        )
        .values(**values),
    )
    if matched != 1:
        job = session.get(GenerationJob, job_id)
        if job is None:
            raise NotFound("任务不存在。")
        raise InvalidJobTransition(f"任务当前状态 {job.status} 不能迁移到 {target}。")

    session.expire_all()
    job = session.get(GenerationJob, job_id)
    if job is None:  # pragma: no cover - the UPDATE just matched this row
        raise NotFound("任务不存在。")
    return job


def request_cancel(
    session: Session, job_id: str, *, now: dt.datetime | None = None
) -> GenerationJob:
    """Marks a cancellation request.

    Cancellation is a request, not a fact: a job already handed to a provider
    may still finish and bill us, and settlement follows the real outcome.
    """
    moment = now or utcnow()
    matched = rows_affected(
        session,
        update(GenerationJob)
        .where(
            GenerationJob.id == job_id,
            GenerationJob.status.in_([s.value for s in CANCELLABLE_JOB_STATUSES]),
            GenerationJob.cancel_requested_at.is_(None),
        )
        .values(cancel_requested_at=moment),
    )
    if matched != 1:
        job = session.get(GenerationJob, job_id)
        if job is None:
            raise NotFound("任务不存在。")
        if job.cancel_requested_at is not None:
            return job
        raise JobNotCancellable(f"任务当前状态 {job.status} 不允许取消。")

    session.expire_all()
    job = session.get(GenerationJob, job_id)
    if job is None:  # pragma: no cover
        raise NotFound("任务不存在。")
    return job


def append_event(
    session: Session,
    job_id: str,
    *,
    event_type: JobEventType,
    status: JobStatus,
    public_message: str,
    progress: int = 0,
    internal_code: str | None = None,
    payload: dict[str, object] | None = None,
    now: dt.datetime | None = None,
) -> JobEvent:
    """Appends the next event in the job's stream.

    `sequence` is derived from the current maximum and protected by a unique
    constraint, so a concurrent writer fails loudly rather than creating a hole
    that would break SSE resumption.
    """
    current_max = session.scalar(
        select(JobEvent.sequence)
        .where(JobEvent.job_id == job_id)
        .order_by(JobEvent.sequence.desc())
        .limit(1)
    )
    event = JobEvent(
        job_id=job_id,
        sequence=(current_max or 0) + 1,
        event_type=event_type,
        status=status,
        progress=max(0, min(100, progress)),
        public_message=public_message,
        internal_code=internal_code,
        payload_json=payload or {},
        created_at=now or utcnow(),
    )
    session.add(event)
    session.flush()
    return event


def events_since(session: Session, job_id: str, after_sequence: int = 0) -> list[JobEvent]:
    """Backfill for an SSE client reconnecting with `Last-Event-ID`."""
    return list(
        session.scalars(
            select(JobEvent)
            .where(JobEvent.job_id == job_id, JobEvent.sequence > after_sequence)
            .order_by(JobEvent.sequence)
        )
    )
