"""Celery task definitions.

Tasks stay thin: they own the session and the retry policy, and delegate all
logic to functions that can be called directly in tests.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from celery import Task
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError, OperationalError

from app.db import session_scope
from app.domain.jobs import input_requests
from app.domain.jobs import service as jobs_service
from app.domain.jobs import state_machine as sm
from app.domain.system_log import service as system_log
from app.models import (
    AsyncProviderTask,
    GenerationJob,
    ReconciliationReport,
    WebhookEvent,
    WorkflowInputRequest,
)
from app.models.base import utcnow
from app.models.enums import JobEventType, JobStatus, SystemLogLevel, SystemLogSource
from app.workers.celery_app import celery_app
from app.workers.pipeline import JobNotFoundError, run_generation_pipeline

logger = logging.getLogger(__name__)

# A job stuck in a non-terminal state past this point is presumed lost.
STALE_JOB_TIMEOUT = dt.timedelta(minutes=30)

# Only these warrant Celery countdown retries. Business crashes are settled by
# the pipeline before re-raise; orphan job ids are permanent and must not retry.
_TRANSIENT_WORKER_ERRORS: tuple[type[BaseException], ...] = (
    ConnectionError,
    TimeoutError,
    OperationalError,
    RedisError,
)


class GenerationTask(Task):
    """Celery task base that cannot strand a job after its final retry.

    Pipeline failures normally settle the job themselves.  This final hook is
    for failures at the task boundary (argument binding, worker setup, or an
    exception before the pipeline can transition the job).
    """

    abstract = True

    def on_failure(
        self,
        exc: BaseException,
        task_id: str,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        einfo: Any,
    ) -> None:
        job_id = str(args[0]) if args else ""
        if job_id:
            _settle_worker_failure(job_id, task_id=task_id, exc=exc)
        super().on_failure(exc, task_id, args, kwargs, einfo)


def _is_transient_worker_error(exc: BaseException) -> bool:
    if isinstance(exc, _TRANSIENT_WORKER_ERRORS):
        return True
    # A dead connection is worth one more attempt; other DBAPI errors are not.
    return isinstance(exc, DBAPIError) and bool(getattr(exc, "connection_invalidated", False))


def _run_generation_task(task: Task, job_id: str) -> str:
    """Execute one job for all latency-specific Celery entrypoints.

    Calling one decorated bound task from another injects Celery's ``self`` a
    second time.  Keeping the shared body undecorated avoids that class of
    failure while preserving separate queue-visible task names.
    """

    with session_scope() as session:
        try:
            outcome = run_generation_pipeline(session, job_id)
        except JobNotFoundError as exc:
            # Broker message left over after a DB truncate/seed --reset: there
            # is nothing to settle and retrying will fail the same way.
            logger.warning("generation task skipped: %s", exc)
            system_log.emit(
                source=SystemLogSource.PIPELINE,
                event="job_missing",
                message=str(exc),
                dedup_key=f"job:{job_id}",
                level=SystemLogLevel.WARNING,
                job_id=job_id,
                details={"exception_type": type(exc).__name__},
            )
            return "missing"
        except Exception as exc:
            if _is_transient_worker_error(exc):
                raise task.retry(exc=exc, countdown=10) from exc
            # Pipeline already released credits and marked the job failed.
            raise
        return outcome.status.value


def _settle_worker_failure(job_id: str, *, task_id: str, exc: BaseException | None = None) -> None:
    try:
        with session_scope() as session:
            job = session.get(GenerationJob, job_id)
            if job is None or JobStatus(job.status).is_terminal:
                return
            sm.transition(
                session,
                job.id,
                JobStatus.FAILED,
                failure_code="WORKER_TASK_FAILED",
                failure_message="生成任务执行失败，积分已退回。",
            )
            jobs_service.settle_release(session, job, reason="worker_task_failed")
            sm.append_event(
                session,
                job.id,
                event_type=JobEventType.FAILED,
                status=JobStatus.FAILED,
                public_message="生成任务执行失败，积分已退回。",
                progress=100,
                internal_code="WORKER_TASK_FAILED",
                payload={"celery_task_id": task_id},
            )
    except Exception:
        logger.exception("could not settle failed Celery task %s for job %s", task_id, job_id)

    # `JobEvent.public_message` above is deliberately generic; the original
    # exception text (retries exhausted, or a fault before the pipeline's own
    # try/except could run) only goes here, where an operator can find it.
    system_log.emit(
        source=SystemLogSource.PIPELINE,
        event="worker_task_failed",
        message=str(exc) if exc is not None else "celery task failed with no exception captured",
        dedup_key=f"job:{job_id}",
        level=SystemLogLevel.ERROR,
        job_id=job_id,
        details={"celery_task_id": task_id, "exception_type": type(exc).__name__ if exc else None},
    )


@celery_app.task(
    name="app.workers.tasks.run_generation", bind=True, base=GenerationTask, max_retries=2
)
def run_generation(self: Task, job_id: str) -> str:
    return _run_generation_task(self, job_id)


@celery_app.task(
    name="app.workers.tasks.run_video_generation",
    bind=True,
    base=GenerationTask,
    max_retries=2,
)
def run_video_generation(self, job_id: str) -> str:  # type: ignore[no-untyped-def]
    return _run_generation_task(self, job_id)


@celery_app.task(
    name="app.workers.tasks.run_audio_generation",
    bind=True,
    base=GenerationTask,
    max_retries=2,
)
def run_audio_generation(self, job_id: str) -> str:  # type: ignore[no-untyped-def]
    return _run_generation_task(self, job_id)


@celery_app.task(name="app.workers.tasks.run_quality_check")
def run_quality_check(job_id: str) -> str:
    with session_scope() as session:
        job = session.get(GenerationJob, job_id)
        return job.status if job else "missing"


@celery_app.task(name="app.workers.tasks.expire_stale_jobs")
def expire_stale_jobs() -> int:
    """Settles jobs whose worker died mid-flight.

    Without this a crash would leave the user's credits reserved forever,
    breaking the "reserve always settles" invariant.
    """
    moment = utcnow()
    cutoff = moment - STALE_JOB_TIMEOUT
    active_external_task = (
        select(AsyncProviderTask.id)
        .where(
            AsyncProviderTask.job_id == GenerationJob.id,
            AsyncProviderTask.deadline_at > moment,
        )
        .exists()
    )
    # A job legitimately `AWAITING_INPUT` always has a row here — its own,
    # much longer, deadline is `expire_stale_input_requests`'s job. Without
    # this exclusion the 30-minute sweep below would expire a question an
    # author simply had not gotten back to yet.
    active_input_request = (
        select(WorkflowInputRequest.id)
        .where(WorkflowInputRequest.job_id == GenerationJob.id)
        .exists()
    )
    expired = 0
    with session_scope() as session:
        stale = session.scalars(
            select(GenerationJob).where(
                GenerationJob.status.in_(
                    [
                        JobStatus.CREATED.value,
                        JobStatus.QUEUED.value,
                        JobStatus.SUBMITTED.value,
                        JobStatus.RUNNING.value,
                        JobStatus.AWAITING_INPUT.value,
                    ]
                ),
                # A retried/recovered job may be older than the work currently
                # executing.  Expire by its last state change, not immutable
                # creation time, and let a live async checkpoint own its own
                # tighter deadline.
                GenerationJob.updated_at < cutoff,
                ~active_external_task,
                ~active_input_request,
            )
        )
        for job in stale:
            # Claim the job first: releasing credits for a job another worker is
            # still running would double-settle the reservation.
            try:
                sm.transition(
                    session,
                    job.id,
                    JobStatus.EXPIRED,
                    failure_code="JOB_EXPIRED",
                    failure_message="任务超时未完成，积分已退回。",
                )
            except Exception:
                logger.exception("could not expire job %s", job.id)
                continue
            jobs_service.settle_release(session, job, reason="expired")
            expired += 1
    return expired


@celery_app.task(name="app.workers.tasks.poll_async_provider_tasks")
def poll_async_provider_tasks() -> int:
    """Advances every job parked on an external render.

    This is the other half of `WorkflowRunner._suspend`: those jobs are
    `RUNNING` with no Celery task in flight, so without this tick they would
    sit there until `expire_stale_jobs` released their credits. Returns how
    many rows this tick actually settled or rescheduled.
    """
    from app.workers.async_polling import poll_once

    with session_scope() as session:
        return poll_once(session)


@celery_app.task(name="app.workers.tasks.expire_stale_input_requests")
def expire_stale_input_requests() -> int:
    """Releases credits for questions nobody came back to answer.

    The `copy_generate` counterpart to `poll_async_provider_tasks`: both are
    the other half of a `WorkflowRunner._suspend` path, but this one has
    nothing to poll — there is only a deadline to check.
    """
    expired = 0
    with session_scope() as session:
        for request in input_requests.due_for_expiry(session):
            job = session.get(GenerationJob, request.job_id)
            if job is None or JobStatus(job.status).is_terminal:
                # Settled by something else already (an admin action, a
                # cancel); nothing left to expire.
                input_requests.settle(session, request)
                session.commit()
                continue
            try:
                sm.transition(
                    session,
                    job.id,
                    JobStatus.EXPIRED,
                    failure_code="INPUT_REQUEST_EXPIRED",
                    failure_message="任务超时未收到回答，积分已退回。",
                )
            except Exception:
                logger.exception("could not expire job %s awaiting input", job.id)
                continue
            jobs_service.settle_release(session, job, reason="input_request_expired")
            sm.append_event(
                session,
                job.id,
                event_type=JobEventType.FAILED,
                status=JobStatus.EXPIRED,
                public_message="任务超时未收到回答，积分已退回。",
                progress=100,
                internal_code="INPUT_REQUEST_EXPIRED",
                node_id=request.node_id,
            )
            input_requests.settle(session, request)
            expired += 1
    return expired


@celery_app.task(name="app.workers.tasks.reconcile_webhooks")
def reconcile_webhooks() -> int:
    """Processes webhook events that arrived but were never handled."""
    with session_scope() as session:
        pending = list(
            session.scalars(select(WebhookEvent).where(WebhookEvent.processed_at.is_(None)))
        )
        for event in pending:
            event.processed_at = utcnow()
        return len(pending)


@celery_app.task(name="app.workers.tasks.reconcile_credits")
def reconcile_credits() -> str:
    """Writes a ledger health snapshot for the ops console."""
    from app.domain.credits import reconciliation

    with session_scope() as session:
        report: ReconciliationReport = reconciliation.build_report(session)
        return report.id


def dispatch_generation(job: GenerationJob) -> None:
    """Routes a job to the queue matching its latency profile.

    Video renders take minutes; putting them on the image queue would block
    every quick job behind them.
    """
    from app.models.enums import Operation

    video_ops = {Operation.TEXT_TO_VIDEO, Operation.IMAGE_TO_VIDEO, Operation.VIDEO_TO_VIDEO}
    if job.operation in video_ops:
        task = run_video_generation
    elif job.operation == Operation.AUDIO_GENERATION:
        task = run_audio_generation
    else:
        task = run_generation
    task.delay(job.id)


__all__ = [
    "dispatch_generation",
    "expire_stale_input_requests",
    "expire_stale_jobs",
    "poll_async_provider_tasks",
    "reconcile_credits",
    "reconcile_webhooks",
    "run_audio_generation",
    "run_generation",
    "run_quality_check",
    "run_video_generation",
]
