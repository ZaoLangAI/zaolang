"""Celery task definitions.

Tasks stay thin: they own the session and the retry policy, and delegate all
logic to functions that can be called directly in tests.
"""

from __future__ import annotations

import contextlib
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
from app.domain.jobs.cancellation import honor_user_cancel
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

# Per-task hard/soft wall-clock budgets (seconds). A queue mixes tasks of very
# different latency profiles (`webhook_reconcile` alone carries everything
# from a single-row lease sweep to a from-scratch retention purge), so these
# are set per task rather than once per worker/queue. `soft_time_limit` lets
# a task raise `SoftTimeLimitExceeded` and unwind through the normal
# exception path (`GenerationTask.on_failure` settles the job exactly like
# any other failure); `time_limit` is the SIGKILL backstop a few seconds
# later for a task that does not unwind in time. Every value here must stay
# comfortably under `celery_app.py`'s `broker_transport_options.
# visibility_timeout`, or a still-legitimately-running task risks a second,
# duplicate delivery.
_QUICK = {"soft_time_limit": 60, "time_limit": 90}
_MODERATE = {"soft_time_limit": 120, "time_limit": 180}
_GENERATION = {"soft_time_limit": 300, "time_limit": 360}
# Image jobs run several reasoning-model judgment calls plus a provider
# render in one Celery task. A single character-kind pass already sits
# near five minutes with glm-5.3-flash; `_GENERATION` (audio) is too tight.
# `dispatch_generation` then adds `_IMAGE_EXTRA_VIEW` per extra
# `character_views` entry (the in-task loop after `asset_output_advance`).
# The cap is the 3-view maximum — stay well under `visibility_timeout`.
_IMAGE_GENERATION = {"soft_time_limit": 420, "time_limit": 480}
_IMAGE_EXTRA_VIEW = {"soft_time_limit": 180, "time_limit": 240}
_IMAGE_GENERATION_CAP = {"soft_time_limit": 780, "time_limit": 960}
_LONG_GENERATION = {"soft_time_limit": 480, "time_limit": 600}
_BATCH = {"soft_time_limit": 300, "time_limit": 450}
# The slowest class: video/audio analysis (watching a whole clip before
# answering) and first-run retention purges over an unbounded backlog.
_SLOW = {"soft_time_limit": 600, "time_limit": 900}

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
    name="app.workers.tasks.run_generation",
    bind=True,
    base=GenerationTask,
    max_retries=2,
    **_IMAGE_GENERATION,
)
def run_generation(self: Task, job_id: str) -> str:
    return _run_generation_task(self, job_id)


@celery_app.task(
    name="app.workers.tasks.run_video_generation",
    bind=True,
    base=GenerationTask,
    max_retries=2,
    **_LONG_GENERATION,
)
def run_video_generation(self, job_id: str) -> str:  # type: ignore[no-untyped-def]
    return _run_generation_task(self, job_id)


@celery_app.task(
    name="app.workers.tasks.run_audio_generation",
    bind=True,
    base=GenerationTask,
    max_retries=2,
    **_GENERATION,
)
def run_audio_generation(self, job_id: str) -> str:  # type: ignore[no-untyped-def]
    return _run_generation_task(self, job_id)


@celery_app.task(
    name="app.workers.tasks.run_video_analysis",
    bind=True,
    base=GenerationTask,
    max_retries=2,
    **_SLOW,
)
def run_video_analysis(self, job_id: str) -> str:  # type: ignore[no-untyped-def]
    return _run_generation_task(self, job_id)


@celery_app.task(name="app.workers.tasks.run_quality_check", **_QUICK)
def run_quality_check(job_id: str) -> str:
    with session_scope() as session:
        job = session.get(GenerationJob, job_id)
        return job.status if job else "missing"


@celery_app.task(name="app.workers.tasks.run_draft_publish", bind=True, max_retries=2, **_MODERATE)
def run_draft_publish(self: Task, draft_id: str) -> str:
    """Finishes a draft publish after the HTTP accept: safety, then Work."""
    from app.domain.publishing import service as publishing

    with session_scope() as session:
        try:
            publishing.finalize_draft_publish(session, draft_id)
        except Exception as exc:
            if _is_transient_worker_error(exc):
                raise self.retry(exc=exc, countdown=10) from exc
            raise
    return "done"


@celery_app.task(name="app.workers.tasks.expire_stale_jobs", **_MODERATE)
def expire_stale_jobs() -> int:
    """Settles jobs whose worker died mid-flight.

    Without this a crash would leave the user's credits reserved forever,
    breaking the "reserve always settles" invariant.
    """
    moment = utcnow()
    cutoff = moment - STALE_JOB_TIMEOUT
    # Existence, not `deadline_at > moment`: the lease is renewed by the
    # *poller*, so exactly when Beat has been down for a while — the one
    # time this sweep matters most — the lease looks exactly as stale as a
    # genuinely abandoned task. Racing `expire_stale_jobs` against the first
    # `poll_async_provider_tasks` tick after Beat comes back had settled real
    # upstream successes as `expired` purely because the sweep's own queue
    # happened to drain first. A parked row is proof of life the same way an
    # `AWAITING_INPUT` row below is: only the poller — which never gives up on
    # a pending render (see `async_polling._advance`) — gets to decide this
    # job's fate.
    active_external_task = (
        select(AsyncProviderTask.id).where(AsyncProviderTask.job_id == GenerationJob.id).exists()
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
            if job.cancel_requested_at is not None:
                try:
                    honor_user_cancel(session, job)
                    expired += 1
                except Exception:
                    logger.exception("could not honour cancel on stale job %s", job.id)
                continue
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


@celery_app.task(name="app.workers.tasks.poll_async_provider_tasks", **_QUICK)
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


@celery_app.task(name="app.workers.tasks.expire_stale_input_requests", **_MODERATE)
def expire_stale_input_requests() -> int:
    """Releases credits for questions nobody came back to answer.

    The `copy_generate` counterpart to `poll_async_provider_tasks`: both are
    the other half of a `WorkflowRunner._suspend` path, but this one has
    nothing to poll — there is only a deadline to check.
    """
    expired = 0
    with session_scope() as session:
        for request in input_requests.due_for_user_cancel(session):
            job = session.get(GenerationJob, request.job_id)
            if job is None or JobStatus(job.status).is_terminal:
                input_requests.settle(session, request)
                session.commit()
                continue
            try:
                honor_user_cancel(session, job, node_id=request.node_id)
            except Exception:
                logger.exception("could not honour cancel for job %s awaiting input", job.id)
                continue
            session.commit()
            expired += 1
        for request in input_requests.due_for_expiry(session):
            job = session.get(GenerationJob, request.job_id)
            if job is None or JobStatus(job.status).is_terminal:
                # Settled by something else already (an admin action, a
                # cancel); nothing left to expire.
                input_requests.settle(session, request)
                session.commit()
                continue
            if job.cancel_requested_at is not None:
                try:
                    honor_user_cancel(session, job, node_id=request.node_id)
                except Exception:
                    logger.exception("could not honour cancel for job %s awaiting input", job.id)
                    continue
                session.commit()
                expired += 1
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


@celery_app.task(name="app.workers.tasks.reconcile_webhooks", **_BATCH)
def reconcile_webhooks() -> int:
    """Processes webhook events that arrived but were never handled."""
    with session_scope() as session:
        pending = list(
            session.scalars(select(WebhookEvent).where(WebhookEvent.processed_at.is_(None)))
        )
        for event in pending:
            event.processed_at = utcnow()
        return len(pending)


@celery_app.task(name="app.workers.tasks.reconcile_credits", **_BATCH)
def reconcile_credits() -> str:
    """Writes a ledger health snapshot for the ops console."""
    from app.domain.credits import reconciliation

    with session_scope() as session:
        report: ReconciliationReport = reconciliation.build_report(session)
        return report.id


@celery_app.task(name="app.workers.tasks.purge_expired_exports", **_BATCH)
def purge_expired_exports() -> int:
    """Deletes the storage object behind export bundles past their retention window."""
    from app.domain.compliance import service as compliance_service

    with session_scope() as session:
        purged = compliance_service.purge_expired_exports(session)
        session.commit()
        return purged


@celery_app.task(name="app.workers.tasks.purge_expired_records", **_SLOW)
def purge_expired_records() -> dict[str, int]:
    """Prunes the append-only tables that have no natural cap of their own.

    Without this, `idempotency_records` / `webhook_events` / `system_logs` /
    `job_events` grow forever — see `app.domain.retention.service` for why
    each one's window was picked and why `AuditLog`/`CreditLedgerEntry` are
    deliberately excluded.
    """
    from app.domain.retention import service as retention_service

    with session_scope() as session:
        counts = {
            "idempotency_records": retention_service.purge_idempotency_records(session),
            "webhook_events": retention_service.purge_webhook_events(session),
            "system_logs": retention_service.purge_system_logs(session),
            "job_events": retention_service.purge_job_events(session),
        }
    total = sum(counts.values())
    if total:
        logger.info("purge_expired_records deleted %s rows: %s", total, counts)
    return counts


@celery_app.task(name="app.workers.tasks.run_media_analysis", **_SLOW)
def run_media_analysis(analysis_id: str) -> str:
    from app.domain.editor import analysis as media_analysis
    from app.domain.errors import NotFound

    with session_scope() as session:
        try:
            row = media_analysis.run_analysis(session, analysis_id)
        except NotFound as exc:
            # Broker message left over after a DB truncate/seed --reset, or a
            # vanished row: nothing to analyse and retrying will fail the same way.
            logger.warning("media analysis task skipped: %s", exc)
            return "missing"
        session.commit()
        return row.status


@celery_app.task(name="app.workers.tasks.run_editor_transcription", **_SLOW)
def run_editor_transcription(analysis_id: str) -> str:
    """Same queue, same row shape, same shrug-and-skip-on-missing-row
    behavior as `run_media_analysis` — this is a second analyzer identity on
    the same `MediaAnalysis` table, not a new pipeline."""
    from app.domain.editor import analysis as media_analysis
    from app.domain.errors import NotFound

    with session_scope() as session:
        try:
            row = media_analysis.run_transcription(session, analysis_id)
        except NotFound as exc:
            logger.warning("editor transcription task skipped: %s", exc)
            return "missing"
        session.commit()
        return row.status


@celery_app.task(name="app.workers.tasks.expire_editor_leases", **_QUICK)
def expire_editor_leases() -> int:
    from sqlalchemy import update

    from app.db import rows_affected
    from app.models import EditorLease
    from app.models.base import utcnow as now

    with session_scope() as session:
        matched = rows_affected(
            session,
            update(EditorLease)
            .where(EditorLease.revoked_at.is_(None), EditorLease.expires_at <= now())
            .values(revoked_at=now()),
        )
        session.commit()
        return matched


@celery_app.task(name="app.workers.tasks.expire_orphan_editor_uploads", **_MODERATE)
def expire_orphan_editor_uploads() -> int:
    """Marks expired editor uploads so they are not completed after the lease dies."""
    from sqlalchemy import select

    from app.models import UploadSession
    from app.models.base import utcnow as now
    from app.storage import s3

    purposes = {"editor_source", "editor_export", "caption", "font"}
    deleted = 0
    with session_scope() as session:
        rows = list(
            session.scalars(
                select(UploadSession).where(
                    UploadSession.purpose.in_(purposes),
                    UploadSession.completed_at.is_(None),
                    UploadSession.expires_at <= now(),
                )
            )
        )
        for row in rows:
            with contextlib.suppress(Exception):
                s3.delete_object(row.object_key)
            session.delete(row)
            deleted += 1
        session.commit()
    return deleted


@celery_app.task(name="app.workers.tasks.pull_episode_metrics", **_BATCH)
def pull_episode_metrics() -> int:
    """Refreshes every submitted post's play/like/comment/share snapshot.

    Runs on its own `platform_distribution` queue/beat schedule, separate from
    the generation-job lifecycle queues — see `app.domain.distribution.
    service.pull_episode_metrics` for the actual pull/upsert logic.
    """
    from app.domain.distribution import service as distribution_service

    with session_scope() as session:
        return distribution_service.pull_episode_metrics(session)


def image_generation_time_limits(job: GenerationJob) -> dict[str, int]:
    """Wall-clock budget for one `run_generation` invocation.

    Multiplies the single-pass floor by how many character views this job
    will loop through in the same Celery task. Anything that is not a
    multi-view `character` job (including a missing `request_json`) is one
    pass. Capped at the 3-view ceiling so a malformed list cannot outrun
    `visibility_timeout`.
    """
    params = job.request_json if isinstance(getattr(job, "request_json", None), dict) else {}
    raw_kind = params.get("asset_kind")
    raw_views = params.get("character_views")
    extra = max(
        jobs_service.character_output_count(
            asset_kind=raw_kind if isinstance(raw_kind, str) else None,
            character_views=raw_views if isinstance(raw_views, list) else None,
        )
        - 1,
        0,
    )
    return {
        "soft_time_limit": min(
            _IMAGE_GENERATION["soft_time_limit"] + _IMAGE_EXTRA_VIEW["soft_time_limit"] * extra,
            _IMAGE_GENERATION_CAP["soft_time_limit"],
        ),
        "time_limit": min(
            _IMAGE_GENERATION["time_limit"] + _IMAGE_EXTRA_VIEW["time_limit"] * extra,
            _IMAGE_GENERATION_CAP["time_limit"],
        ),
    }


def dispatch_generation(job: GenerationJob) -> None:
    """Routes a job to the queue matching its latency profile.

    Video renders take minutes; putting them on the image queue would block
    every quick job behind them. Image jobs also carry a per-invocation
    time limit: a multi-view character completion loops the generate
    cycle in one task, so `apply_async` stretches the default budget.
    """
    from app.models.enums import Operation

    video_ops = {Operation.TEXT_TO_VIDEO, Operation.IMAGE_TO_VIDEO, Operation.VIDEO_TO_VIDEO}
    if job.operation in video_ops:
        run_video_generation.delay(job.id)
        return
    if job.operation == Operation.AUDIO_GENERATION:
        run_audio_generation.delay(job.id)
        return
    if job.operation == Operation.VIDEO_ANALYSIS:
        run_video_analysis.delay(job.id)
        return
    run_generation.apply_async((job.id,), **image_generation_time_limits(job))


__all__ = [
    "dispatch_generation",
    "expire_stale_input_requests",
    "expire_stale_jobs",
    "image_generation_time_limits",
    "poll_async_provider_tasks",
    "reconcile_credits",
    "reconcile_webhooks",
    "run_audio_generation",
    "run_draft_publish",
    "run_generation",
    "run_quality_check",
    "run_video_analysis",
    "run_video_generation",
]
