"""Generation jobs, quoting and the SSE progress stream."""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, DbSession, IdempotencyKey, rate_limited
from app.api.schemas.common import Page
from app.api.schemas.jobs import (
    GenerationJobCreateRequest,
    GenerationJobResponse,
    JobAnswerRequest,
    JobEventResponse,
    JobInputQuestionView,
    JobInputRequestResponse,
    PromoteJobRequest,
    QuoteRequest,
    QuoteResponse,
    RouteSummary,
)
from app.domain.credits import service as credits_service
from app.domain.errors import NotFound, ValidationFailed
from app.domain.jobs import input_requests
from app.domain.jobs import service as jobs_service
from app.domain.jobs import state_machine as sm
from app.domain.licensing import service as licensing
from app.models import Draft, GenerationJob, Work, WorkflowInputRequest, WorkVersion
from app.models.base import new_id
from app.models.enums import JobEventType, JobStatus, Operation, QualityTier
from app.presenters import media_urls
from app.realtime import publisher
from app.workflows.types import WorkflowContext

router = APIRouter(tags=["generation"])

SSE_HEARTBEAT_SECONDS = 15
SSE_MAX_DURATION_SECONDS = 600

VIDEO_OPERATIONS = {Operation.TEXT_TO_VIDEO, Operation.IMAGE_TO_VIDEO, Operation.VIDEO_TO_VIDEO}


@router.post("/generation-jobs/quote", response_model=QuoteResponse)
def quote(payload: QuoteRequest, user: CurrentUser, session: DbSession) -> QuoteResponse:
    """Price preview. Must be shown before any credits are committed."""
    priced = jobs_service.quote_for(
        session,
        operation=payload.operation,
        quality_tier=payload.quality_tier,
        duration_seconds=payload.duration_seconds,
    )
    account = credits_service.get_or_create_account(session, user.id)
    session.commit()
    return QuoteResponse(
        credits=priced.credits,
        estimated_seconds=priced.estimated_seconds,
        breakdown=priced.breakdown,
        available_credits=account.available_balance,
        sufficient=account.available_balance >= priced.credits,
    )


@router.post("/generation-jobs", response_model=GenerationJobResponse, status_code=202)
def create_job(
    payload: GenerationJobCreateRequest,
    user: CurrentUser,
    session: DbSession,
    idempotency_key: IdempotencyKey,
    _: Annotated[None, Depends(rate_limited("generation_submit"))],
) -> GenerationJobResponse:
    """Submits a job: quote, reserve, enqueue.

    Credits are reserved inside this transaction so the user cannot queue more
    work than they can pay for, even by submitting in parallel.
    """
    if payload.operation in VIDEO_OPERATIONS:
        from app.platform_config import service as config_service

        if not config_service.is_enabled(session, "video_generation", user_id=user.id):
            raise ValidationFailed("视频生成暂未开放。")

    source_version_id = _resolve_source_version(session, payload, user.id)

    result = jobs_service.submit(
        session,
        user_id=user.id,
        operation=payload.operation,
        quality_tier=payload.quality_tier,
        params=payload.params.model_dump(),
        idempotency_key=idempotency_key or new_id("idk"),
        draft_id=payload.draft_id,
        source_work_version_id=source_version_id,
        max_credits=payload.max_credits,
    )
    if payload.draft_id:
        draft = session.get(Draft, payload.draft_id)
        if draft is not None and draft.user_id == user.id:
            draft.latest_job_id = result.job.id
    session.commit()

    if not result.replayed:
        _enqueue(result.job)
    return _job_response(session, result.job, include_events=True)


@router.get("/generation-jobs", response_model=Page[GenerationJobResponse])
def list_jobs(
    user: CurrentUser,
    session: DbSession,
    status: JobStatus | None = None,
    limit: int = Query(default=20, ge=1, le=50),
) -> Page[GenerationJobResponse]:
    stmt = (
        select(GenerationJob)
        .where(GenerationJob.user_id == user.id)
        .order_by(GenerationJob.created_at.desc())
        .limit(limit)
    )
    if status is not None:
        stmt = stmt.where(GenerationJob.status == status)
    jobs = list(session.scalars(stmt))
    return Page(items=[_job_response(session, job) for job in jobs])


@router.get("/generation-jobs/{job_id}", response_model=GenerationJobResponse)
def get_job(job_id: str, user: CurrentUser, session: DbSession) -> GenerationJobResponse:
    job = jobs_service.get_owned_job(session, job_id, user.id)
    return _job_response(session, job, include_events=True)


@router.post("/generation-jobs/{job_id}/cancel", response_model=GenerationJobResponse)
def cancel_job(job_id: str, user: CurrentUser, session: DbSession) -> GenerationJobResponse:
    """Requests cancellation.

    A job already at the provider may still complete; settlement follows the
    real outcome rather than the request.
    """
    job = jobs_service.get_owned_job(session, job_id, user.id)
    job = sm.request_cancel(session, job.id)
    session.commit()
    return _job_response(session, job, include_events=True)


@router.post(
    "/generation-jobs/{job_id}/retry", response_model=GenerationJobResponse, status_code=202
)
def retry_job(
    job_id: str,
    user: CurrentUser,
    session: DbSession,
    idempotency_key: IdempotencyKey,
) -> GenerationJobResponse:
    """Resubmits a failed job as a new one.

    A new job (rather than reopening the old one) keeps the ledger honest: the
    first attempt's release and the retry's reserve stay separate records.
    """
    original = jobs_service.get_owned_job(session, job_id, user.id)
    if original.status not in (JobStatus.FAILED, JobStatus.CANCELLED, JobStatus.EXPIRED):
        raise ValidationFailed("只有失败或已取消的任务可以重试。")

    result = jobs_service.submit(
        session,
        user_id=user.id,
        operation=original.operation,
        quality_tier=original.quality_tier,
        params=dict(original.request_json),
        idempotency_key=idempotency_key or new_id("idk"),
        draft_id=original.draft_id,
        source_work_version_id=original.source_work_version_id,
        max_credits=original.max_credits,
    )
    result.job.retry_of_job_id = original.id
    session.commit()

    if not result.replayed:
        _enqueue(result.job)
    return _job_response(session, result.job, include_events=True)


@router.post(
    "/generation-jobs/{job_id}/promote", response_model=GenerationJobResponse, status_code=202
)
def promote_job(
    job_id: str,
    payload: PromoteJobRequest,
    user: CurrentUser,
    session: DbSession,
    idempotency_key: IdempotencyKey,
    _: Annotated[None, Depends(rate_limited("generation_submit"))],
) -> GenerationJobResponse:
    """Upgrades a succeeded preview-tier job to a full deep-generation job.

    A new job (rather than reopening the preview) keeps the ledger honest, same
    reasoning as `retry_job` — the preview's reservation and the deep job's
    reservation stay separate records.
    """
    original = jobs_service.get_owned_job(session, job_id, user.id)
    if original.status != JobStatus.SUCCEEDED or QualityTier(original.quality_tier) != (
        QualityTier.PREVIEW
    ):
        raise ValidationFailed("只有成功的预览任务可以升级为正式生成。")

    result = jobs_service.submit(
        session,
        user_id=user.id,
        operation=original.operation,
        quality_tier=payload.quality_tier,
        params=dict(original.request_json),
        idempotency_key=idempotency_key or new_id("idk"),
        draft_id=original.draft_id,
        source_work_version_id=original.source_work_version_id,
        max_credits=payload.max_credits,
    )
    result.job.promoted_from_job_id = original.id
    if original.draft_id:
        draft = session.get(Draft, original.draft_id)
        if draft is not None and draft.user_id == user.id:
            draft.latest_job_id = result.job.id
    session.commit()

    if not result.replayed:
        _enqueue(result.job)
    return _job_response(session, result.job, include_events=True)


@router.get(
    "/generation-jobs/{job_id}/input-request", response_model=JobInputRequestResponse
)
def get_input_request(job_id: str, user: CurrentUser, session: DbSession) -> JobInputRequestResponse:
    """The follow-up questions a `copy_generate` node is waiting on.

    404 both when the job has no pending request and when it belongs to
    someone else — `get_owned_job` already refuses to reveal the latter.
    """
    job = jobs_service.get_owned_job(session, job_id, user.id)
    request = input_requests.find_for_job(session, job.id)
    if request is None:
        raise NotFound("没有待回答的问题。")
    return JobInputRequestResponse(
        job_id=job.id,
        node_id=request.node_id,
        questions=[JobInputQuestionView(**q) for q in request.questions_json],
        expires_at=request.expires_at,
    )


@router.post("/generation-jobs/{job_id}/answer", response_model=GenerationJobResponse)
def answer_job_input(
    job_id: str,
    payload: JobAnswerRequest,
    user: CurrentUser,
    session: DbSession,
) -> GenerationJobResponse:
    """Answers a `copy_generate` node's follow-up questions and resumes the job.

    Mirrors `app.workers.async_polling._resume_succeeded`'s rebuild-context-
    then-resume shape, but runs inline in the request rather than off a
    scheduler tick: unlike a provider render, nothing else is going to come
    back and finish this for the user.
    """
    job = jobs_service.get_owned_job(session, job_id, user.id)
    if JobStatus(job.status) != JobStatus.AWAITING_INPUT:
        raise ValidationFailed("当前任务不在等待回答的状态。")
    request = input_requests.find_for_job(session, job.id)
    if request is None:
        raise NotFound("没有待回答的问题。")

    raw_answers = {item.question_id: item.value for item in payload.answers}
    answers = input_requests.validate_answers(request.questions_json, raw_answers)

    ctx = _resume_context(session, job, request)
    output = dict(ctx.state.get(request.output_key) or {})
    output["clarify_answers"] = answers
    ctx.state[request.output_key] = output
    node_id = request.node_id

    input_requests.settle(session, request)
    job = sm.transition(session, job.id, JobStatus.RUNNING)
    ctx.job = job
    event = sm.append_event(
        session,
        job.id,
        event_type=JobEventType.PROGRESS,
        status=JobStatus.RUNNING,
        public_message="已收到你的回答，正在继续生成",
        progress=jobs_service.progress_for(session, job),
        node_id=node_id,
    )
    session.commit()
    publisher.publish_job_event(
        job.id,
        {
            "sequence": event.sequence,
            "event_type": event.event_type,
            "status": event.status,
            "progress": event.progress,
            "message": event.public_message,
        },
    )

    _resume(job, ctx, node_id=node_id)
    session.commit()
    session.refresh(job)
    return _job_response(session, job, include_events=True)


@router.get("/generation-jobs/{job_id}/events")
def stream_events(
    job_id: str,
    request: Request,
    user: CurrentUser,
    session: DbSession,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> StreamingResponse:
    """Server-sent progress stream.

    On reconnect the client sends `Last-Event-ID` and receives every missed
    event from the database before the live tail resumes, so no progress step
    is ever silently skipped.
    """
    jobs_service.get_owned_job(session, job_id, user.id)
    after = _parse_last_event_id(last_event_id)

    # Read the backfill here rather than inside the generator: it is a bounded
    # query, and doing it while the request session is still open avoids opening
    # a second connection that would be held for the life of the stream.
    backfill: list[dict[str, Any]] = [
        {
            "sequence": event.sequence,
            "event_type": event.event_type,
            "status": event.status,
            "progress": event.progress,
            "message": event.public_message,
        }
        for event in sm.events_since(session, job_id, after)
    ]

    def generate() -> Iterator[str]:
        started = time.monotonic()
        last_sequence = after

        for payload in backfill:
            last_sequence = int(payload["sequence"])
            yield _sse(last_sequence, payload)

        if backfill and JobStatus(str(backfill[-1]["status"])).is_terminal:
            # The job finished before the client connected, so there is nothing
            # left to wait for; holding the connection open would occupy a
            # worker for no reason.
            return

        last_heartbeat = time.monotonic()
        for payload in publisher.subscribe(job_id):
            if time.monotonic() - started > SSE_MAX_DURATION_SECONDS:
                break
            if not payload:
                if time.monotonic() - last_heartbeat > SSE_HEARTBEAT_SECONDS:
                    last_heartbeat = time.monotonic()
                    yield ": heartbeat\n\n"
                continue

            sequence = int(payload.get("sequence", 0))
            # Pub/sub can deliver an event the backfill already sent.
            if sequence <= last_sequence:
                continue
            last_sequence = sequence
            yield _sse(sequence, payload)
            if payload.get("status") in {s.value for s in JobStatus if s.is_terminal}:
                break

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "cache-control": "no-cache",
            "connection": "keep-alive",
            "x-accel-buffering": "no",
        },
    )


def _sse(event_id: int, payload: dict[str, object]) -> str:
    return f"id: {event_id}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _parse_last_event_id(value: str | None) -> int:
    if not value:
        return 0
    try:
        return max(0, int(value))
    except ValueError:
        return 0


def _resolve_source_version(
    session: Session, payload: GenerationJobCreateRequest, user_id: str
) -> str | None:
    if payload.draft_id:
        draft = session.get(Draft, payload.draft_id)
        if draft is None or draft.user_id != user_id:
            raise NotFound("草稿不存在。")
        return draft.source_work_version_id
    if payload.source_work_id:
        work = session.get(Work, payload.source_work_id)
        if work is None:
            raise NotFound("来源作品不存在。")
        # Re-checked here so the API cannot be used to bypass the UI's guard.
        licensing.assert_remixable(work, user_id)
        version = session.get(WorkVersion, work.current_version_id or "")
        return version.id if version else None
    return None


def _enqueue(job: GenerationJob) -> None:
    from app.workers import tasks

    tasks.dispatch_generation(job)


def _resume_context(
    session: Session, job: GenerationJob, request: WorkflowInputRequest
) -> WorkflowContext:
    """Rebuilds the workflow state a `copy_generate` suspension had.

    Only the JSON-safe slice written by `_input_checkpoint` is restored; a
    live routing decision, if any ran before this node, was never part of it
    and stays whatever `route_score` would recompute on its own next visit.
    """
    params = dict(job.request_json)
    ctx = WorkflowContext(
        session=session, job=job, prompt=str(params.get("prompt", "")), params=params
    )
    checkpoint = dict(request.state_checkpoint_json or {})
    ctx.state[request.output_key] = dict(checkpoint.get("output_value") or {})
    ctx.state["attempt_number"] = int(checkpoint.get("attempt_number") or 1)
    ctx.state["route_attempts"] = int(checkpoint.get("route_attempts") or 1)
    ctx.state["tried_providers"] = set(checkpoint.get("tried_providers") or ())
    ctx.state["intent_hint"] = dict(checkpoint.get("intent_hint") or {})
    return ctx


def _resume(job: GenerationJob, ctx: WorkflowContext, *, node_id: str) -> None:
    """Continues the graph from where `copy_generate` left off.

    A local import, same reasoning as `_enqueue`: `app.workers.pipeline`
    pulls in the workflow engine and domain services this module must not
    import at module load time to avoid a cycle with `app.workers.tasks`.
    """
    from app.workers.pipeline import resolve_graph
    from app.workflows.runner import WorkflowRunner

    WorkflowRunner(resolve_graph(ctx.session, job)).resume(ctx, node_id=node_id, port="ok")


def _job_response(
    session: Session, job: GenerationJob, *, include_events: bool = False
) -> GenerationJobResponse:
    route = job.selected_route_summary_json or {}
    events: list[JobEventResponse] = []
    if include_events:
        events = [
            JobEventResponse(
                sequence=e.sequence,
                event_type=e.event_type,
                status=JobStatus(e.status),
                progress=e.progress,
                message=e.public_message,
                internal_code=e.internal_code,
                created_at=e.created_at,
            )
            for e in sm.events_since(session, job.id, 0)
        ]

    return GenerationJobResponse(
        id=job.id,
        status=JobStatus(job.status),
        operation=Operation(job.operation),
        quality_tier=job.quality_tier,
        progress=jobs_service.progress_for(session, job),
        quoted_credits=job.quoted_credits,
        reserved_credits=job.reserved_credits,
        actual_credits=job.actual_credits,
        estimated_seconds=job.estimated_seconds,
        route=RouteSummary(**route) if route else None,
        output_asset_id=job.output_asset_id,
        output_url=media_urls.asset_url(session, job.output_asset_id),
        output_media_type=media_urls.media_type_of(session, job.output_asset_id),
        draft_id=job.draft_id,
        failure_code=job.failure_code,
        failure_message=job.failure_message,
        cancel_requested=job.cancel_requested_at is not None,
        promoted_from_job_id=job.promoted_from_job_id,
        created_at=job.created_at,
        finished_at=job.finished_at,
        events=events,
    )
