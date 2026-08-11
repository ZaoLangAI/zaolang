"""Park a generation job on an external provider task and resume it later.

`WorkflowRunner` calls `suspend` when a node hands work outside the worker
process (today: AiHubMix video). The beat task `poll_async_provider_tasks`
owns the schedule and calls `claim_due` / `WorkflowRunner.resume` once the
upstream settles — those helpers live here so neither the runner nor the task
talks to the table directly.

Claiming follows the same principle as `state_machine.transition`: the check
and the write are one conditional UPDATE, so two scheduler ticks racing for
the same row produce exactly one winner. Without that, both would resume the
same workflow and the job would be settled twice.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db import rows_affected
from app.models import AsyncProviderTask
from app.models.base import utcnow

logger = logging.getLogger(__name__)

# Platform policy, not a provider's: how often to check on an external render,
# and when to call it stuck rather than merely slow. The timeout must stay
# well under `app.workers.tasks.STALE_JOB_TIMEOUT`, or the stale-job sweeper
# would expire a job that is still legitimately rendering.
POLL_INTERVAL_SECONDS = 15
TASK_TIMEOUT_SECONDS = 480

# How long one tick may hold a row before another may take it over.
# Comfortably longer than a poll plus a download, short enough that a worker
# killed mid-tick does not strand the render.
CLAIM_LEASE = dt.timedelta(minutes=5)


def suspend(
    session: Session,
    *,
    job_id: str,
    node_id: str,
    checkpoint: dict[str, Any],
    now: dt.datetime | None = None,
) -> AsyncProviderTask:
    """Writes the row that proves a `RUNNING` job is still owned by someone.

    `checkpoint` is the JSON-safe dict produced by
    `app.workflows.nodes._provider_checkpoint`: capability + external id +
    the request/state slices the resumed walk needs.
    """
    moment = now or utcnow()
    existing = find_for_job(session, job_id)
    if existing is not None:
        # A job runs one provider attempt at a time; replacing keeps the
        # unique constraint honest if a retry re-submits before the previous
        # row was cleaned up.
        session.delete(existing)
        session.flush()

    row = AsyncProviderTask(
        job_id=job_id,
        node_id=node_id,
        capability_name=str(checkpoint.get("capability_name") or ""),
        external_task_id=str(checkpoint.get("external_task_id") or ""),
        request_json=dict(checkpoint.get("request") or {}),
        state_checkpoint_json=dict(checkpoint.get("state") or {}),
        provider_attempt_id=checkpoint.get("provider_attempt_id"),
        next_poll_at=moment + dt.timedelta(seconds=POLL_INTERVAL_SECONDS),
        deadline_at=moment + dt.timedelta(seconds=TASK_TIMEOUT_SECONDS),
        poll_count=0,
        claimed_at=None,
    )
    session.add(row)
    session.flush()
    return row


def find_for_job(session: Session, job_id: str) -> AsyncProviderTask | None:
    return session.scalar(select(AsyncProviderTask).where(AsyncProviderTask.job_id == job_id))


def claim_due(
    session: Session, *, limit: int = 50, now: dt.datetime | None = None
) -> list[AsyncProviderTask]:
    """Takes ownership of the tasks whose next check is due.

    Rows are claimed one conditional UPDATE at a time rather than in a single
    statement, so a row another tick just took is simply skipped instead of
    failing the whole batch.
    """
    moment = now or utcnow()
    lease_cutoff = moment - CLAIM_LEASE
    due = list(
        session.scalars(
            select(AsyncProviderTask)
            .where(AsyncProviderTask.next_poll_at <= moment)
            .order_by(AsyncProviderTask.next_poll_at)
            .limit(limit)
        )
    )

    claimed: list[AsyncProviderTask] = []
    for row in due:
        won = rows_affected(
            session,
            update(AsyncProviderTask)
            .where(
                AsyncProviderTask.id == row.id,
                AsyncProviderTask.next_poll_at <= moment,
                (AsyncProviderTask.claimed_at.is_(None))
                | (AsyncProviderTask.claimed_at < lease_cutoff),
            )
            .values(claimed_at=moment),
        )
        if won:
            session.refresh(row)
            claimed.append(row)
    session.flush()
    return claimed


def reschedule(
    session: Session, task: AsyncProviderTask, *, now: dt.datetime | None = None
) -> None:
    """Releases the claim and books the next check."""
    moment = now or utcnow()
    task.poll_count += 1
    task.next_poll_at = moment + dt.timedelta(seconds=POLL_INTERVAL_SECONDS)
    task.claimed_at = None
    session.flush()


def settle(session: Session, task: AsyncProviderTask) -> None:
    """Drops the row once the external task is no longer in flight.

    Deleting rather than flagging: the row exists to say "someone still has
    to come back for this job", and a settled one has no readers. The durable
    record of what happened is `ProviderAttempt` plus the job's own events.
    """
    session.delete(task)
    session.flush()
