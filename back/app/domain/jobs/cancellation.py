"""Honour a user cancel request once it is safe to stop the job.

`request_cancel` only stamps `cancel_requested_at`. This module is the single
place that turns that stamp into `CANCELLED`, a released reservation, and a
stream event — API, the workflow runner, the async poller, and the input-
request sweeper all call here so those paths cannot drift.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.domain.errors import InvalidJobTransition
from app.domain.jobs import async_tasks, input_requests
from app.domain.jobs import service as jobs_service
from app.domain.jobs import state_machine as sm
from app.models import AsyncProviderTask, GenerationJob, JobEvent
from app.models.enums import JobEventType, JobStatus
from app.realtime import publisher

logger = logging.getLogger(__name__)

_CANCELLED_MESSAGE = "任务已取消，积分已退回"
_ACK_MESSAGE = "已收到取消请求"


def should_honor_immediately(session: Session, job: GenerationJob) -> bool:
    """True when nothing is mid-flight inside a worker process.

    `QUEUED` and a `RUNNING` job with no async checkpoint stay as a request:
    a worker may be inside an LLM call or a synchronous `submit()`. Parked
    states — never started, waiting on the author, or waiting on an upstream
    render — can stop in the same request.
    """
    status = JobStatus(job.status)
    if status in (JobStatus.AWAITING_INPUT, JobStatus.CREATED):
        return True
    if status in (JobStatus.RUNNING, JobStatus.SUBMITTED):
        return async_tasks.find_for_job(session, job.id) is not None
    return False


def honor_user_cancel(
    session: Session, job: GenerationJob, *, node_id: str | None = None
) -> GenerationJob:
    """Settles a cancel request: drop parked work, release credits, go terminal.

    Safe to call more than once. A job that is already terminal, or that never
    had `cancel_requested_at` set, is returned unchanged.
    """
    if JobStatus(job.status).is_terminal:
        return job
    if job.cancel_requested_at is None:
        return job

    request = input_requests.find_for_job(session, job.id)
    if request is not None:
        if node_id is None:
            node_id = request.node_id
        input_requests.settle(session, request)

    task = async_tasks.find_for_job(session, job.id)
    if task is not None:
        if node_id is None:
            node_id = task.node_id
        _cancel_async_task(session, task)

    jobs_service.settle_release(session, job, reason="cancelled_by_user")
    try:
        job = sm.transition(session, job.id, JobStatus.CANCELLED)
    except InvalidJobTransition:
        session.refresh(job)
        return job

    _emit_cancelled(session, job, node_id=node_id)
    return job


def ack_cancel_request(
    session: Session, job: GenerationJob, *, node_id: str | None = None
) -> GenerationJob:
    """Tells the stream a cancel was recorded but the job is still walking."""
    event = sm.append_event(
        session,
        job.id,
        event_type=JobEventType.PROGRESS,
        status=JobStatus(job.status),
        public_message=_ACK_MESSAGE,
        progress=jobs_service.progress_for(session, job),
        node_id=node_id,
    )
    _publish(job.id, event, cancel_requested=True)
    return job


def _cancel_async_task(session: Session, task: AsyncProviderTask) -> None:
    from app.agents import router

    capability = router.build_catalog(session).get(task.capability_name)
    if capability is None:
        logger.warning(
            "honor_user_cancel: capability %s missing for async task %s (job %s)",
            task.capability_name,
            task.id,
            task.job_id,
        )
        async_tasks.settle(session, task)
        return
    async_tasks.cancel_upstream(session, task, capability.provider_factory())


def _emit_cancelled(session: Session, job: GenerationJob, *, node_id: str | None) -> None:
    event = sm.append_event(
        session,
        job.id,
        event_type=JobEventType.CANCELLED,
        status=JobStatus.CANCELLED,
        public_message=_CANCELLED_MESSAGE,
        progress=100,
        node_id=node_id,
    )
    _publish(job.id, event, cancel_requested=True)


def _publish(job_id: str, event: JobEvent, *, cancel_requested: bool) -> None:
    publisher.publish_job_event(
        job_id,
        {
            "sequence": event.sequence,
            "event_type": event.event_type,
            "status": event.status,
            "progress": event.progress,
            "message": event.public_message,
            "node_id": event.node_id,
            "cancel_requested": cancel_requested,
        },
    )
