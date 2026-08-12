"""Job operations: search, full replay, forced termination and requeue."""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from fastapi import APIRouter, Query, Request
from sqlalchemy import func, or_, select

from app.agents import router as intent_router
from app.api.deps import DbSession
from app.api.request_utils import as_utc
from app.api.schemas.admin import (
    AdminJobDetail,
    AdminJobSummary,
    AgentRunView,
    AsyncProviderTaskView,
    JobEventView,
    JobStatsView,
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
from app.domain.errors import Conflict, NotFound, ValidationFailed
from app.domain.jobs import async_tasks
from app.domain.jobs import service as jobs_service
from app.domain.jobs import state_machine as sm
from app.domain.system_log import service as system_log
from app.models import (
    AgentProfile,
    AgentRun,
    AsyncProviderTask,
    GenerationJob,
    JobEvent,
    Profile,
    ProviderAttempt,
)
from app.models.base import utcnow
from app.models.enums import JobEventType, JobStatus, SystemLogLevel, SystemLogSource
from app.platform_config import service as config_service
from app.platform_config.schemas import LlmProviderConfig, LlmProviderEndpoint

router = APIRouter(tags=["admin:jobs"])
logger = logging.getLogger(__name__)

# A job stuck in a non-terminal state for longer than this is a candidate for
# operator intervention; the pipeline's own expiry sweep uses the same window.
# Also how far past its own `AsyncProviderTask.deadline_at` a task must be
# before the list marks the job `stuck` — the same order of magnitude as "an
# operator should look at this", not a second, independently-tuned knob.
STUCK_AFTER_MINUTES = 30


@router.get("/jobs", response_model=Page[AdminJobSummary])
def list_jobs(
    session: DbSession,
    user: Viewer,
    _: AdminRead,
    status: str | None = None,
    user_query: str | None = Query(default=None, alias="user"),
    provider: str | None = None,
    stuck_only: bool = False,
    created_after: dt.datetime | None = None,
    created_before: dt.datetime | None = None,
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> Page[AdminJobSummary]:
    stmt = select(GenerationJob).order_by(GenerationJob.created_at.desc(), GenerationJob.id.desc())
    if status:
        stmt = stmt.where(GenerationJob.status.in_(_parse_statuses(status)))
    if user_query:
        stmt = stmt.where(_user_match(user_query))
    if provider:
        stmt = stmt.where(
            GenerationJob.id.in_(
                select(ProviderAttempt.job_id).where(
                    _provider_match(session, provider, ProviderAttempt.provider)
                )
            )
        )
    if created_after:
        stmt = stmt.where(GenerationJob.created_at >= as_utc(created_after))
    if created_before:
        stmt = stmt.where(GenerationJob.created_at <= as_utc(created_before))
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

    job_ids = [job.id for job in page]
    profiles = _profiles_by_user(session, [job.user_id for job in page])
    attempt_counts = _attempt_counts(session, job_ids)
    stuck_ids = _stuck_job_ids(session, job_ids)
    endpoints = config_service.get_typed(session, "llm_providers", LlmProviderConfig).endpoints

    return Page(
        items=[
            _build_summary(
                job,
                attempt_count=attempt_counts.get(job.id, 0),
                profile=profiles.get(job.user_id),
                provider_label=_provider_label(
                    endpoints, job.selected_route_summary_json.get("provider")
                ),
                stuck=job.id in stuck_ids,
            )
            for job in page
        ],
        next_cursor=page[-1].id if has_more and page else None,
        has_more=has_more,
    )


@router.get("/jobs/stats", response_model=JobStatsView)
def job_stats(
    session: DbSession,
    user: Viewer,
    _: AdminRead,
    hours: int = Query(default=24, ge=1, le=720),
) -> JobStatsView:
    """Throughput for the statistics hub: status/operation mix and how long a
    succeeded job actually takes, over a rolling window.

    Declared before `/jobs/{job_id}` so FastAPI's path matching does not treat
    `stats` as a job id.
    """
    cutoff = utcnow() - dt.timedelta(hours=hours)
    rows = session.execute(
        select(
            GenerationJob.status,
            GenerationJob.operation,
            GenerationJob.created_at,
            GenerationJob.finished_at,
        ).where(GenerationJob.created_at >= cutoff)
    ).all()

    by_status: dict[str, int] = {}
    by_operation: dict[str, int] = {}
    completion_ms: list[float] = []
    for status, operation, created_at, finished_at in rows:
        by_status[status] = by_status.get(status, 0) + 1
        by_operation[operation] = by_operation.get(operation, 0) + 1
        if (
            status == JobStatus.SUCCEEDED.value
            and finished_at is not None
            and created_at is not None
        ):
            completion_ms.append((as_utc(finished_at) - as_utc(created_at)).total_seconds() * 1000)

    return JobStatsView(
        generated_at=utcnow(),
        window_hours=hours,
        by_status=by_status,
        by_operation=by_operation,
        total_jobs=len(rows),
        avg_completion_ms=(sum(completion_ms) / len(completion_ms)) if completion_ms else None,
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
    agent_runs = list(
        session.scalars(
            select(AgentRun).where(AgentRun.job_id == job.id).order_by(AgentRun.created_at)
        )
    )
    endpoints = config_service.get_typed(session, "llm_providers", LlmProviderConfig).endpoints
    agent_display_names = _agent_display_names(
        session, [r.agent_profile_id for r in agent_runs if r.agent_profile_id]
    )
    task = async_tasks.find_for_job(session, job.id)

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
                node_id=e.node_id,
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
            AgentRunView(
                id=r.id,
                agent_name=r.agent_name,
                agent_profile_id=r.agent_profile_id,
                agent_display_name=(
                    agent_display_names.get(r.agent_profile_id) if r.agent_profile_id else None
                ),
                prompt_slot=r.prompt_slot,
                model=r.model or "",
                mode=r.mode,
                degraded=r.degraded,
                prompt_tokens=r.prompt_tokens,
                completion_tokens=r.completion_tokens,
                latency_ms=r.latency_ms,
                status=r.status,
                job_id=r.job_id,
                node_id=r.node_id,
                created_at=r.created_at,
            )
            for r in agent_runs
        ],
        async_task=(
            AsyncProviderTaskView(
                node_id=task.node_id,
                capability_name=task.capability_name,
                provider_label=_provider_label(endpoints, task.capability_name),
                external_task_id=task.external_task_id,
                poll_count=task.poll_count,
                next_poll_at=task.next_poll_at,
                deadline_at=task.deadline_at,
                claimed_at=task.claimed_at,
                provider_attempt_id=task.provider_attempt_id,
            )
            if task is not None
            else None
        ),
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
    upstream_cancel_attempted, upstream_cancel_succeeded = _cancel_in_flight_task(session, job)

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
        after={
            "status": job.status,
            "released": payload.release_credits,
            "upstream_cancel_attempted": upstream_cancel_attempted,
            "upstream_cancel_succeeded": upstream_cancel_succeeded,
        },
        reason=payload.reason,
        request=request,
    )
    session.commit()
    return job_detail(job.id, session, user, None)


def _cancel_in_flight_task(session, job: GenerationJob) -> tuple[bool, bool | None]:  # type: ignore[no-untyped-def]
    """Best-effort upstream notification for `terminate`, synchronous with it.

    Mirrors `async_polling.py::_cancel()`'s use of `cancel_upstream`, but
    called from an admin request instead of a poll tick — an operator forcing
    a job that is still rendering upstream must not leave the provider
    unaware, waiting minutes for a poll that will never come because the job
    is already terminal. Returns `(attempted, succeeded)`; `succeeded` is
    `None` when there was nothing to attempt.
    """
    task = async_tasks.find_for_job(session, job.id)
    if task is None:
        return False, None

    try:
        capability = intent_router.build_catalog(session).get(task.capability_name)
        if capability is None:
            logger.warning(
                "admin terminate: capability %s for job %s is no longer in the catalogue",
                task.capability_name,
                job.id,
            )
            system_log.emit(
                source=SystemLogSource.PIPELINE,
                event="admin_terminate_capability_missing",
                message=(
                    f"capability {task.capability_name} missing from catalogue at admin terminate"
                ),
                dedup_key=f"job:{job.id}",
                level=SystemLogLevel.WARNING,
                job_id=job.id,
                details={"capability_name": task.capability_name},
            )
            return True, False
        succeeded = async_tasks.cancel_upstream(session, task, capability.provider_factory())
    except Exception as exc:
        # `cancel_upstream` itself never raises past its own try/except; a
        # raise here means the catalogue/factory call above did. Either way,
        # termination must proceed — this is best-effort notification, not a
        # precondition for the state transition below.
        logger.exception("admin terminate: failed to cancel upstream task for job %s", job.id)
        system_log.emit(
            source=SystemLogSource.PIPELINE,
            event="admin_terminate_cancel_failed",
            message=f"upstream cancel failed at admin terminate: {exc}",
            dedup_key=f"job:{job.id}",
            level=SystemLogLevel.ERROR,
            job_id=job.id,
        )
        return True, False
    finally:
        # The row must not outlive this request either way: the job is
        # about to become terminal, and nothing will ever poll it again.
        if async_tasks.find_for_job(session, job.id) is not None:
            async_tasks.settle(session, task)
    return True, succeeded


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
                node_id=e.node_id,
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
    """Single-job path for `job_detail`/`terminate`/`requeue`.

    `list_jobs` does not call this — it batches the same lookups across the
    whole page instead of repeating them per row.
    """
    endpoints = config_service.get_typed(session, "llm_providers", LlmProviderConfig).endpoints
    return _build_summary(
        job,
        attempt_count=_attempt_counts(session, [job.id]).get(job.id, 0),
        profile=_profiles_by_user(session, [job.user_id]).get(job.user_id),
        provider_label=_provider_label(endpoints, job.selected_route_summary_json.get("provider")),
        stuck=job.id in _stuck_job_ids(session, [job.id]),
    )


def _build_summary(
    job: GenerationJob,
    *,
    attempt_count: int,
    profile: Profile | None,
    provider_label: str | None,
    stuck: bool,
) -> AdminJobSummary:
    return AdminJobSummary(
        id=job.id,
        user_id=job.user_id,
        user_display_name=profile.display_name if profile else None,
        user_handle=profile.handle if profile else None,
        status=JobStatus(job.status),
        operation=job.operation,
        quality_tier=job.quality_tier,
        provider=job.selected_route_summary_json.get("provider"),
        provider_label=provider_label,
        routing_reason=job.selected_route_summary_json.get("reason"),
        quoted_credits=job.quoted_credits,
        actual_credits=job.actual_credits,
        attempt_count=attempt_count,
        failure_code=job.failure_code,
        created_at=job.created_at,
        finished_at=job.finished_at,
        stuck=stuck,
        workflow_template_id=job.workflow_template_id,
    )


def _profiles_by_user(session, user_ids: list[str]) -> dict[str, Profile]:  # type: ignore[no-untyped-def]
    if not user_ids:
        return {}
    rows = session.scalars(select(Profile).where(Profile.user_id.in_(set(user_ids))))
    return {row.user_id: row for row in rows}


def _attempt_counts(session, job_ids: list[str]) -> dict[str, int]:  # type: ignore[no-untyped-def]
    if not job_ids:
        return {}
    rows = session.execute(
        select(ProviderAttempt.job_id, func.count())
        .where(ProviderAttempt.job_id.in_(job_ids))
        .group_by(ProviderAttempt.job_id)
    ).all()
    return {job_id: int(count) for job_id, count in rows}


def _stuck_job_ids(session, job_ids: list[str]) -> set[str]:  # type: ignore[no-untyped-def]
    """Jobs whose live `AsyncProviderTask` is well past its own deadline.

    Not "still rendering" (that is normal, expected latency) — this is the
    poller having had a full `STUCK_AFTER_MINUTES`-sized window to give up
    on it and apparently not having done so.
    """
    if not job_ids:
        return set()
    cutoff = utcnow() - dt.timedelta(minutes=STUCK_AFTER_MINUTES)
    rows = session.scalars(
        select(AsyncProviderTask.job_id).where(
            AsyncProviderTask.job_id.in_(job_ids), AsyncProviderTask.deadline_at < cutoff
        )
    )
    return set(rows)


def _agent_display_names(session, agent_profile_ids: list[str]) -> dict[str, str]:  # type: ignore[no-untyped-def]
    if not agent_profile_ids:
        return {}
    rows = session.scalars(select(AgentProfile).where(AgentProfile.id.in_(set(agent_profile_ids))))
    return {row.id: row.display_name for row in rows}


def _provider_label(endpoints: dict[str, LlmProviderEndpoint], provider: str | None) -> str | None:
    """Turns `f"{endpoint_id}:{capability}"` into a human label.

    Falls back to `None` (not the raw value) when the endpoint has since
    been renamed away or deleted — the frontend keeps showing the raw
    `provider`/`capability_name` field in that case rather than a stale name.
    """
    if not provider:
        return None
    endpoint_id, _, tag = provider.partition(":")
    endpoint = endpoints.get(endpoint_id)
    if endpoint is None:
        return None
    return f"{endpoint.name} · {tag}" if tag else endpoint.name


def _parse_statuses(raw: str) -> list[str]:
    """`status` filter: comma-separated so the multiselect in the console can
    pass several values through one query param (`?status=queued,running`)
    while staying a plain shareable string like every other filter here.
    """
    values = [part.strip() for part in raw.split(",") if part.strip()]
    known = {s.value for s in JobStatus}
    unknown = [v for v in values if v not in known]
    if unknown:
        raise ValidationFailed(f"未知的任务状态: {', '.join(unknown)}")
    return values


def _user_match(needle: str) -> Any:
    """`user` filter: matches a pasted (partial) `user_id` as well as a
    fuzzy hit on the profile's handle or display name — an operator may have
    either on hand when they start looking for a job.
    """
    needle_like = f"%{needle}%"
    return or_(
        GenerationJob.user_id.ilike(needle_like),
        GenerationJob.user_id.in_(
            select(Profile.user_id).where(
                or_(Profile.handle.ilike(needle_like), Profile.display_name.ilike(needle_like))
            )
        ),
    )


def _provider_match(session, needle: str, column):  # type: ignore[no-untyped-def]
    """`provider` filter: substring on the raw routing key, OR'd with a
    reverse lookup by the endpoint's human name — an operator typing the
    name they see in the console should find the same jobs as one typing
    the raw `endpoint_id:capability` key.
    """
    endpoints = config_service.get_typed(session, "llm_providers", LlmProviderConfig).endpoints
    needle_fold = needle.casefold()
    matched_endpoint_ids = [
        endpoint_id
        for endpoint_id, endpoint in endpoints.items()
        if needle_fold in endpoint.name.casefold()
    ]
    conditions = [column.ilike(f"%{needle}%")]
    conditions.extend(column.startswith(f"{endpoint_id}:") for endpoint_id in matched_endpoint_ids)
    return or_(*conditions)
