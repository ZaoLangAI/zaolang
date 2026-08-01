"""Celery task definitions.

Tasks stay thin: they own the session and the retry policy, and delegate all
logic to functions that can be called directly in tests.
"""

from __future__ import annotations

import datetime as dt
import logging

from sqlalchemy import select

from app.db import session_scope
from app.domain.jobs import service as jobs_service
from app.domain.jobs import state_machine as sm
from app.models import GenerationJob, ReconciliationReport, WebhookEvent
from app.models.base import utcnow
from app.models.enums import JobStatus
from app.workers.celery_app import celery_app
from app.workers.pipeline import run_generation_pipeline

logger = logging.getLogger(__name__)

# A job stuck in a non-terminal state past this point is presumed lost.
STALE_JOB_TIMEOUT = dt.timedelta(minutes=30)


@celery_app.task(name="app.workers.tasks.run_generation", bind=True, max_retries=2)
def run_generation(self, job_id: str) -> str:  # type: ignore[no-untyped-def]
    with session_scope() as session:
        try:
            outcome = run_generation_pipeline(session, job_id)
        except Exception as exc:
            # The pipeline has already released credits and marked the job
            # failed; retrying only re-attempts transient infrastructure faults.
            raise self.retry(exc=exc, countdown=10) from exc
        return outcome.status.value


@celery_app.task(name="app.workers.tasks.run_video_generation", bind=True, max_retries=2)
def run_video_generation(self, job_id: str) -> str:  # type: ignore[no-untyped-def]
    return run_generation(self, job_id)


@celery_app.task(name="app.workers.tasks.run_moderation")
def run_moderation(subject_type: str, subject_id: str) -> str:
    from app.agents import safety
    from app.models.enums import ModerationStage

    with session_scope() as session:
        result = safety.review(
            session,
            text=f"{subject_type}:{subject_id}",
            stage=ModerationStage.POST_GENERATION,
            subject_type=subject_type,
            subject_id=subject_id,
        )
        return str(result.status)


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
    cutoff = utcnow() - STALE_JOB_TIMEOUT
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
                    ]
                ),
                GenerationJob.created_at < cutoff,
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
    task = run_video_generation if job.operation in video_ops else run_generation
    task.delay(job.id)


__all__ = [
    "dispatch_generation",
    "expire_stale_jobs",
    "reconcile_credits",
    "reconcile_webhooks",
    "run_generation",
    "run_moderation",
    "run_quality_check",
    "run_video_generation",
]
