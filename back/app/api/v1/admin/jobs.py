"""Job operations: search, full replay, forced termination and requeue."""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Query, Request
from sqlalchemy import func, select

from app.api.deps import DbSession
from app.api.schemas.admin import (
    AdminJobDetail,
    AdminJobSummary,
    JobEventView,
    JobTerminateRequest,
    ProviderAttemptView,
)
from app.api.schemas.common import Page
from app.api.v1.admin.deps import (
    AdminDangerous,
    AdminRead,
    AdminWrite,
    Operator,
    Viewer,
    require_confirmation,
)
from app.domain.audit import service as audit
from app.domain.errors import Conflict, NotFound
from app.domain.jobs import service as jobs_service
from app.domain.jobs import state_machine as sm
from app.models import AgentRun, GenerationJob, JobEvent, ProviderAttempt
from app.models.base import utcnow
from app.models.enums import JobEventType, JobStatus

router = APIRouter(tags=["admin:jobs"])

# A job stuck in a non-terminal state for longer than this is a candidate for
# operator intervention; the pipeline's own expiry sweep uses the same window.
STUCK_AFTER_MINUTES = 30


@router.get("/jobs", response_model=Page[AdminJobSummary])
def list_jobs(
    session: DbSession,
    user: Viewer,
    _: AdminRead,
    status: JobStatus | None = None,
    user_id: str | None = None,
    provider: str | None = None,
    stuck_only: bool = False,
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> Page[AdminJobSummary]:
    stmt = select(GenerationJob).order_by(GenerationJob.created_at.desc(), GenerationJob.id.desc())
    if status:
        stmt = stmt.where(GenerationJob.status == status)
    if user_id:
        stmt = stmt.where(GenerationJob.user_id == user_id)
    if provider:
        stmt = stmt.where(
            GenerationJob.id.in_(
                select(ProviderAttempt.job_id).where(ProviderAttempt.provider == provider)
            )
        )
    if stuck_only:
        cutoff = utcnow() - dt.timedelta(minutes=STUCK_AFTER_MINUTES)
        stmt = stmt.where(
            GenerationJob.status.notin_([s.value for s in JobStatus if s.is_terminal]),
            GenerationJob.created_at < cutoff,
        )
    if cursor:
        stmt = stmt.where(GenerationJob.id < cursor)

    rows = list(session.scalars(stmt.limit(limit + 1)))
    has_more = len(rows) > limit
    page = rows[:limit]
    return Page(
        items=[_summary(session, job) for job in page],
        next_cursor=page[-1].id if has_more and page else None,
        has_more=has_more,
    )


@router.get("/jobs/{job_id}", response_model=AdminJobDetail)
def job_detail(job_id: str, session: DbSession, user: Viewer, _: AdminRead) -> AdminJobDetail:
    """Everything needed to explain one job after the fact."""
    job = _load(session, job_id)
    events = session.scalars(
        select(JobEvent).where(JobEvent.job_id == job.id).order_by(JobEvent.sequence)
    )
    attempts = session.scalars(
        select(ProviderAttempt)
        .where(ProviderAttempt.job_id == job.id)
        .order_by(ProviderAttempt.attempt_number)
    )
    agent_runs = session.scalars(
        select(AgentRun).where(AgentRun.job_id == job.id).order_by(AgentRun.created_at)
    )

    return AdminJobDetail(
        **_summary(session, job).model_dump(),
        params=job.request_json,
        routing_trace=list(job.routing_trace_json or []),
        events=[
            JobEventView(
                sequence=e.sequence,
                event_type=e.event_type,
                status=e.status,
                progress=e.progress,
                message=e.public_message,
                internal_code=e.internal_code,
                payload=e.payload_json,
                created_at=e.created_at,
            )
            for e in events
        ],
        attempts=[
            ProviderAttemptView(
                id=a.id,
                attempt_number=a.attempt_number,
                provider=a.provider,
                status=a.status,
                latency_ms=a.latency_ms,
                cost_credits=a.cost_minor,
                error_code=a.failure_code,
                error_message=str(a.raw_metadata_redacted_json.get("error", "")) or None,
                created_at=a.created_at,
            )
            for a in attempts
        ],
        agent_runs=[
            {
                "id": r.id,
                "agent_name": r.agent_name,
                "model": r.model,
                "mode": r.mode,
                "degraded": r.degraded,
                "degrade_reason": r.degrade_reason,
                "latency_ms": r.latency_ms,
                "status": r.status,
                "output": r.output_json,
                "created_at": r.created_at,
            }
            for r in agent_runs
        ],
    )


@router.post("/jobs/{job_id}/terminate", response_model=AdminJobDetail)
def terminate(
    job_id: str,
    payload: JobTerminateRequest,
    request: Request,
    session: DbSession,
    user: Operator,
    _: AdminDangerous,
) -> AdminJobDetail:
    """Forces a stuck job into a terminal state.

    The move still goes through the state machine, so a job that finished a
    moment earlier is not overwritten, and reserved credits are returned to the
    user unless the operator explicitly keeps them held.
    """
    require_confirmation(payload.confirm)
    job = _load(session, job_id)
    if JobStatus(job.status).is_terminal:
        raise Conflict("任务已经处于终态。")

    before = {"status": job.status}
    job = sm.transition(
        session,
        job.id,
        JobStatus.CANCELLED,
        failure_code="ADMIN_TERMINATED",
        failure_message="任务被运营人员强制终止。",
    )
    sm.append_event(
        session,
        job.id,
        event_type=JobEventType.CANCELLED,
        status=JobStatus.CANCELLED,
        public_message="任务已被平台终止。",
        progress=100,
        internal_code="ADMIN_TERMINATED",
    )
    if payload.release_credits:
        jobs_service.settle_release(session, job, reason=payload.reason)

    audit.record(
        session,
        actor=user,
        action="job.force_terminate",
        target_type="generation_job",
        target_id=job.id,
        before=before,
        after={"status": job.status, "released": payload.release_credits},
        reason=payload.reason,
        request=request,
    )
    session.commit()
    return job_detail(job.id, session, user, None)


@router.post("/jobs/{job_id}/requeue", response_model=AdminJobDetail)
def requeue(
    job_id: str,
    request: Request,
    session: DbSession,
    user: Operator,
    _: AdminWrite,
) -> AdminJobDetail:
    """Re-dispatches a job whose worker died before reaching a terminal state.

    Only non-terminal jobs qualify; replaying a finished job would risk a second
    capture against the same reservation.
    """
    job = _load(session, job_id)
    if JobStatus(job.status).is_terminal:
        raise Conflict("终态任务不能重放，请让用户重新提交。")

    from app.workers import tasks

    sm.append_event(
        session,
        job.id,
        event_type=JobEventType.QUEUED,
        status=JobStatus(job.status),
        public_message="任务已重新排队。",
        progress=2,
        internal_code="ADMIN_REQUEUED",
    )
    audit.record(
        session,
        actor=user,
        action="job.requeue",
        target_type="generation_job",
        target_id=job.id,
        before={"status": job.status},
        after={"status": job.status},
        request=request,
    )
    session.commit()
    tasks.dispatch_generation(job)
    return job_detail(job.id, session, user, None)


@router.get("/jobs/{job_id}/events", response_model=Page[JobEventView])
def job_events(
    job_id: str,
    session: DbSession,
    user: Viewer,
    _: AdminRead,
    after_sequence: int = 0,
) -> Page[JobEventView]:
    _load(session, job_id)
    events = sm.events_since(session, job_id, after_sequence)
    return Page(
        items=[
            JobEventView(
                sequence=e.sequence,
                event_type=e.event_type,
                status=e.status,
                progress=e.progress,
                message=e.public_message,
                internal_code=e.internal_code,
                payload=e.payload_json,
                created_at=e.created_at,
            )
            for e in events
        ]
    )


def _load(session, job_id: str) -> GenerationJob:  # type: ignore[no-untyped-def]
    job = session.get(GenerationJob, job_id)
    if job is None:
        raise NotFound("任务不存在。")
    return job


def _summary(session, job: GenerationJob) -> AdminJobSummary:  # type: ignore[no-untyped-def]
    attempt_count = int(
        session.scalar(
            select(func.count())
            .select_from(ProviderAttempt)
            .where(ProviderAttempt.job_id == job.id)
        )
        or 0
    )
    return AdminJobSummary(
        id=job.id,
        user_id=job.user_id,
        status=JobStatus(job.status),
        operation=job.operation,
        quality_tier=job.quality_tier,
        provider=job.selected_route_summary_json.get("provider"),
        quoted_credits=job.quoted_credits,
        actual_credits=job.actual_credits,
        attempt_count=attempt_count,
        failure_code=job.failure_code,
        created_at=job.created_at,
        finished_at=job.finished_at,
    )
