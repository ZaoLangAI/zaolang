"""Handing a submitted job to the worker, and cleaning up if that fails.

Lives in the domain rather than beside one route because two surfaces now
submit jobs — the generation studios (`api/v1/jobs.py`) and the canvas Agent
(`domain/canvas/agent_service.py`) — and both need the identical broker-outage
behaviour. Duplicating it would eventually leave one of them stranding credit
reservations that the other releases.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.domain.errors import ProviderTemporaryFailure
from app.domain.jobs import service as jobs_service
from app.domain.jobs import state_machine as sm
from app.models import GenerationJob
from app.models.enums import JobEventType, JobStatus

ENQUEUE_FAILED_MESSAGE = "任务入队失败，积分已退回，请重试。"


def enqueue(job: GenerationJob) -> None:
    from app.workers import tasks

    tasks.dispatch_generation(job)


def enqueue_or_fail(session: Session, job: GenerationJob) -> None:
    """Enqueues the Celery task, failing the job and releasing its reservation
    if the broker itself is unreachable.

    Credits were reserved inside the transaction that just committed
    (`jobs_service.submit`); a broker outage here must not leave that
    reservation stuck for the ~30 minutes it would take `expire_stale_jobs`
    to notice on its own.
    """
    try:
        enqueue(job)
    except Exception as exc:
        sm.transition(
            session,
            job.id,
            JobStatus.FAILED,
            failure_code="ENQUEUE_FAILED",
            failure_message=ENQUEUE_FAILED_MESSAGE,
        )
        jobs_service.settle_release(session, job, reason="enqueue_failed")
        sm.append_event(
            session,
            job.id,
            event_type=JobEventType.FAILED,
            status=JobStatus.FAILED,
            public_message=ENQUEUE_FAILED_MESSAGE,
            progress=100,
            internal_code="ENQUEUE_FAILED",
        )
        session.commit()
        raise ProviderTemporaryFailure("任务入队失败，请重试。") from exc
