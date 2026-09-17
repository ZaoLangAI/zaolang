"""Generation jobs, quoting and the SSE progress stream."""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, defer

from app.agents import router as routing
from app.api import sse_quota
from app.api.deps import CurrentUser, DbSession, IdempotencyKey, rate_limited
from app.api.schemas.common import Page
from app.api.schemas.jobs import (
    IMAGE_OPERATIONS,
    GenerationJobCreateRequest,
    GenerationJobResponse,
    GenerationModelListResponse,
    GenerationModelOption,
    JobAnswerRequest,
    JobEventResponse,
    JobInputQuestionView,
    JobInputRequestResponse,
    PromoteJobRequest,
    QuoteRequest,
    QuoteResponse,
    RouteSummary,
    VideoAnalysisResult,
)
from app.domain.credits import service as credits_service
from app.domain.errors import NotFound, ValidationFailed
from app.domain.jobs import dispatch as job_dispatch
from app.domain.jobs import input_requests
from app.domain.jobs import service as jobs_service
from app.domain.jobs import state_machine as sm
from app.domain.jobs.cancellation import (
    ack_cancel_request,
    honor_user_cancel,
    should_honor_immediately,
)
from app.domain.licensing import service as licensing
from app.models import Asset, Draft, GenerationJob, Work, WorkVersion
from app.models.base import new_id
from app.models.enums import (
    CharacterViewAngle,
    ImageAssetKind,
    JobOrigin,
    JobStatus,
    MediaGenerationKind,
    Operation,
    QualityTier,
    VideoAssetKind,
)
from app.presenters import media_urls
from app.providers import model_catalog
from app.providers.base import (
    STUDIO_RESOLUTION_TIERS,
    ProviderCapability,
    studio_resolution_tiers,
    studio_tier_for_literal,
)
from app.realtime import publisher

router = APIRouter(tags=["generation"])

SSE_HEARTBEAT_SECONDS = 15
SSE_MAX_DURATION_SECONDS = 600

VIDEO_OPERATIONS = {Operation.TEXT_TO_VIDEO, Operation.IMAGE_TO_VIDEO, Operation.VIDEO_TO_VIDEO}
# The one operation set `GenerationParams.forced_model` accepts (see
# `validate_generation_params`) — the C-end model picker must offer exactly
# the same scope, or a client could pick a model this operation would reject.
_FORCED_MODEL_OPERATIONS = (
    IMAGE_OPERATIONS | frozenset(VIDEO_OPERATIONS) | frozenset({Operation.AUDIO_GENERATION})
)


def _merged_studio_resolutions(
    capabilities: list[ProviderCapability], *, video: bool
) -> list[str] | None:
    """Union of client-facing tiers this model can honour for the operation.

    `None` = unrestricted (image ops, or any candidate without a profile).
    """

    if not video:
        return None
    unrestricted = False
    tiers: set[str] = set()
    for capability in capabilities:
        if capability.resolutions is None:
            unrestricted = True
            continue
        mapped = studio_resolution_tiers(capability.resolutions)
        if mapped:
            tiers.update(mapped)
    if unrestricted:
        return None
    return [tier for tier in STUDIO_RESOLUTION_TIERS if tier in tiers]


def _merged_default_resolution(
    capabilities: list[ProviderCapability], *, video: bool
) -> str | None:
    if not video:
        return None
    for capability in capabilities:
        mapped = studio_tier_for_literal(capability.default_resolution)
        if mapped is not None:
            return mapped
    return None


@router.post("/generation-jobs/quote", response_model=QuoteResponse)
def quote(payload: QuoteRequest, user: CurrentUser, session: DbSession) -> QuoteResponse:
    """Price preview. Must be shown before any credits are committed."""
    priced = jobs_service.quote_for(
        session,
        operation=payload.operation,
        quality_tier=payload.quality_tier,
        duration_seconds=payload.duration_seconds,
        output_count=jobs_service.character_output_count(
            asset_kind=payload.asset_kind.value, character_views=payload.character_views
        ),
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


@router.get("/generation-jobs/models", response_model=GenerationModelListResponse)
def list_generation_models(
    operation: Operation, user: CurrentUser, session: DbSession
) -> GenerationModelListResponse:
    """Read-only model list for `GenerationParams.forced_model`'s studio
    picker — one entry per distinct `ProviderCapability.model_or_workflow`
    enabled for this operation, sourced live from the exact same
    `router.build_catalog` snapshot `route_score` filters against, so an
    operator adding/disabling an endpoint at `/admin/models` is reflected
    here on the very next request rather than a stale/hardcoded list. Never
    exposes `base_url`/`api_key`/`endpoint_id` — only the model name, a
    best-effort display label, and (for video) the client-facing
    `resolutions` / `default_resolution` studio tiers used to preview
    downward adaptation. `768P` never leaves this endpoint.

    Calls `routing.build_catalog` through the module (never a directly
    imported name) so this always resolves whatever `app.agents.router
    .build_catalog` currently is — late-bound, the same way `app.workflows
    .nodes` calls `router.route`. A `from ... import build_catalog` alias
    would freeze onto whichever function object existed the moment this
    module was first imported, silently ignoring any later rebinding of the
    module attribute (harmless in production, which never rebinds it, but a
    real bug against `tests.conftest.fake_media_catalog`'s monkeypatch).
    """
    if operation not in _FORCED_MODEL_OPERATIONS:
        raise ValidationFailed("仅支持图片创作/视频创作/音频创作的模型列表。")
    catalog = routing.build_catalog(session)
    grouped: dict[str, list[ProviderCapability]] = {}
    labels: dict[str, str] = {}
    hide_edit_class = operation in {
        Operation.TEXT_TO_VIDEO,
        Operation.IMAGE_TO_VIDEO,
    }
    for capability in catalog.values():
        if operation.value not in capability.operations:
            continue
        if hide_edit_class and capability.generation_kind == MediaGenerationKind.EDIT:
            continue
        grouped.setdefault(capability.model_or_workflow, []).append(capability)
        labels.setdefault(
            capability.model_or_workflow,
            model_catalog.display_name_for_model(capability.model_or_workflow)
            or capability.model_or_workflow,
        )
    is_video = operation in VIDEO_OPERATIONS
    is_audio = operation == Operation.AUDIO_GENERATION

    def _voices(model: str) -> list[str] | None:
        if not is_audio:
            return None
        voices = model_catalog.voices_for_model(model)
        return list(voices) if voices else None

    options = [
        GenerationModelOption(
            model=model,
            label=labels[model],
            resolutions=_merged_studio_resolutions(capabilities, video=is_video),
            default_resolution=_merged_default_resolution(capabilities, video=is_video),
            voices=_voices(model),
        )
        for model, capabilities in grouped.items()
    ]
    options.sort(key=lambda option: option.label)
    return GenerationModelListResponse(models=options)


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
    if payload.operation == Operation.VIDEO_ANALYSIS:
        from app.platform_config import service as config_service

        if not config_service.is_enabled(session, "video_analysis_enabled", user_id=user.id):
            raise ValidationFailed("视频解析暂未开放。")

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
    session.commit()

    if not result.replayed:
        _enqueue_or_fail(session, result.job)
    return _job_response(session, result.job, include_events=True)


@router.get("/generation-jobs", response_model=Page[GenerationJobResponse])
def list_jobs(
    user: CurrentUser,
    session: DbSession,
    status: JobStatus | None = None,
    draft_id: str | None = None,
    operation: Operation | None = None,
    limit: int = Query(default=20, ge=1, le=50),
) -> Page[GenerationJobResponse]:
    """Lists the user's own jobs, optionally scoped to one draft or operation.

    `draft_id` is how the image studio's inline version-history strip lists
    every iteration generated under the same creative draft — the
    `user_id`/`origin` filters below already keep this from leaking another
    user's jobs even if a foreign draft id is passed. `operation` is how the
    "视频解析" tool's history panel lists only its own jobs
    (`operation=video_analysis`), without a `draft_id` to scope by — that
    tool never creates one.
    """
    stmt = (
        select(GenerationJob)
        # Neither ever reaches `_job_response`'s output — `routing_trace_json`
        # is ops-console-only replay data, and `graph_override_json` is a
        # sandbox-only snapshot excluded from this list by the `origin`
        # filter below anyway. Deferring both means this list, unlike the
        # admin job console, never pays to read them off disk.
        .options(defer(GenerationJob.routing_trace_json), defer(GenerationJob.graph_override_json))
        .where(
            GenerationJob.user_id == user.id,
            GenerationJob.origin != JobOrigin.SANDBOX,
        )
        .order_by(GenerationJob.created_at.desc())
    )
    if status is not None:
        stmt = stmt.where(GenerationJob.status == status)
    if draft_id is not None:
        # Version history lists every iteration under one draft — hide
        # tombstoned versions and use the full 50-item window so a long
        # refine chain is not truncated at the generic list default of 20.
        stmt = stmt.where(
            GenerationJob.draft_id == draft_id,
            GenerationJob.draft_history_hidden_at.is_(None),
        )
        limit = 50
    if operation is not None:
        stmt = stmt.where(GenerationJob.operation == operation.value)
    jobs = list(session.scalars(stmt.limit(limit)))
    return Page(items=_job_responses(session, jobs))


@router.get("/generation-jobs/{job_id}", response_model=GenerationJobResponse)
def get_job(job_id: str, user: CurrentUser, session: DbSession) -> GenerationJobResponse:
    job = jobs_service.get_owned_job(session, job_id, user.id)
    return _job_response(session, job, include_events=True)


@router.post("/generation-jobs/{job_id}/cancel", response_model=GenerationJobResponse)
def cancel_job(job_id: str, user: CurrentUser, session: DbSession) -> GenerationJobResponse:
    """Requests cancellation.

    Parked jobs (never started, waiting on the author, or waiting on an
    upstream render) stop in this request. A worker that is mid-node only
    records the request; the runner honours it at the next boundary.
    """
    job = jobs_service.get_owned_job(session, job_id, user.id)
    already_requested = job.cancel_requested_at is not None
    job = sm.request_cancel(session, job.id)
    if should_honor_immediately(session, job):
        job = honor_user_cancel(session, job)
    elif not already_requested:
        ack_cancel_request(session, job)
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
        _enqueue_or_fail(session, result.job)
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
    session.commit()

    if not result.replayed:
        _enqueue_or_fail(session, result.job)
    return _job_response(session, result.job, include_events=True)


@router.get("/generation-jobs/{job_id}/input-request", response_model=JobInputRequestResponse)
def get_input_request(
    job_id: str, user: CurrentUser, session: DbSession
) -> JobInputRequestResponse:
    """The follow-up questions a planning/`copy_generate` node is waiting on.

    404 both when the job has no pending request and when it belongs to
    someone else — `get_owned_job` already refuses to reveal the latter,
    including every `origin=sandbox` try-it (those answer through admin).
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
    """Answers a planning/`copy_generate` node's follow-up and resumes the job.

    Mirrors `app.workers.async_polling._resume_succeeded`'s rebuild-context-
    then-resume shape, but runs inline in the request rather than off a
    scheduler tick: unlike a provider render, nothing else is going to come
    back and finish this for the user.
    """
    job = jobs_service.get_owned_job(session, job_id, user.id)
    raw_answers = {item.question_id: item.value for item in payload.answers}
    job = input_requests.answer(session, job, raw_answers)
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
    stream_slot = sse_quota.reserve("job_events", user.id)

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
            "node_id": event.node_id,
        }
        for event in sm.events_since(session, job_id, after)
    ]

    def generate() -> Iterator[str]:
        started = time.monotonic()
        last_sequence = after

        try:
            for payload in backfill:
                last_sequence = int(payload["sequence"])
                yield _sse(last_sequence, payload)

            if backfill and JobStatus(str(backfill[-1]["status"])).is_terminal:
                # The job finished before the client connected, so there is
                # nothing left to wait for; holding the connection open would
                # occupy a worker for no reason.
                return

            last_heartbeat = time.monotonic()
            for payload in publisher.subscribe(job_id):
                if time.monotonic() - started > SSE_MAX_DURATION_SECONDS:
                    break
                if not payload:
                    if time.monotonic() - last_heartbeat > SSE_HEARTBEAT_SECONDS:
                        last_heartbeat = time.monotonic()
                        sse_quota.touch("job_events", user.id, stream_slot)
                        yield ": heartbeat\n\n"
                    continue

                if payload.get("event_type") == "thinking":
                    # Live-only: no `id:`, does not advance Last-Event-ID.
                    yield _sse_live(payload)
                    continue
                sequence = int(payload.get("sequence", 0))
                # Pub/sub can deliver an event the backfill already sent.
                if sequence <= last_sequence:
                    continue
                last_sequence = sequence
                yield _sse(sequence, payload)
                if payload.get("status") in {s.value for s in JobStatus if s.is_terminal}:
                    break
        finally:
            sse_quota.release("job_events", user.id, stream_slot)

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


def _sse_live(payload: dict[str, object]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


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
        licensing.assert_remixable(work, user_id, session)
        version = session.get(WorkVersion, work.current_version_id or "")
        return version.id if version else None
    return None


def _enqueue(job: GenerationJob) -> None:
    """Kept as a name the tests already monkeypatch; the behaviour moved to
    `domain.jobs.dispatch` so the canvas Agent submits through the same path."""
    job_dispatch.enqueue(job)


def _enqueue_or_fail(session: Session, job: GenerationJob) -> None:
    job_dispatch.enqueue_or_fail(session, job)


def _job_responses(session: Session, jobs: list[GenerationJob]) -> list[GenerationJobResponse]:
    """Batched `_job_response` for list responses: one bulk asset prefetch plus
    one bulk progress query for the whole page, instead of several queries
    per row (`progress_for`'s `ORDER BY ... LIMIT 1`, and one `session.get`
    per distinct asset id via `media_urls`)."""
    if not jobs:
        return []

    asset_ids: set[str] = set()
    for job in jobs:
        if job.output_asset_id:
            asset_ids.add(job.output_asset_id)
        if job.output_asset_ids_json:
            asset_ids.update(job.output_asset_ids_json)
        reference_id = _first_reference_asset_id(job)
        if reference_id:
            asset_ids.add(reference_id)
    if asset_ids:
        session.execute(select(Asset).where(Asset.id.in_(asset_ids)))

    progress_by_job = jobs_service.progress_for_batch(session, jobs)
    return [_job_response(session, job, progress=progress_by_job.get(job.id)) for job in jobs]


def _job_response(
    session: Session,
    job: GenerationJob,
    *,
    include_events: bool = False,
    progress: int | None = None,
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
                node_id=e.node_id,
            )
            for e in sm.events_since(session, job.id, 0)
        ]

    return GenerationJobResponse(
        id=job.id,
        status=JobStatus(job.status),
        operation=Operation(job.operation),
        quality_tier=job.quality_tier,
        progress=progress if progress is not None else jobs_service.progress_for(session, job),
        quoted_credits=job.quoted_credits,
        reserved_credits=job.reserved_credits,
        actual_credits=job.actual_credits,
        estimated_seconds=job.estimated_seconds,
        route=RouteSummary(**route) if route else None,
        output_asset_id=job.output_asset_id,
        output_url=media_urls.asset_url(session, job.output_asset_id),
        output_media_type=media_urls.media_type_of(session, job.output_asset_id),
        output_asset_ids=job.output_asset_ids_json or None,
        output_urls=(
            [
                url
                for asset_id in job.output_asset_ids_json
                if (url := media_urls.asset_url(session, asset_id))
            ]
            or None
        )
        if job.output_asset_ids_json
        else None,
        reference_url=_reference_url_of(session, job),
        asset_kind=_asset_kind_of(job),
        video_asset_kind=_video_asset_kind_of(job),
        forced_model=_forced_model_of(job),
        character_views=_character_views_of(job),
        duration_seconds=_duration_seconds_of(job),
        linked_character_id=job.linked_character_id,
        linked_scene_id=job.linked_scene_id,
        draft_id=job.draft_id,
        prompt=_prompt_of(job),
        analysis=_analysis_of(job),
        failure_code=job.failure_code,
        failure_message=job.failure_message,
        cancel_requested=job.cancel_requested_at is not None,
        promoted_from_job_id=job.promoted_from_job_id,
        created_at=job.created_at,
        finished_at=job.finished_at,
        events=events,
    )


def _prompt_of(job: GenerationJob) -> str | None:
    params = job.request_json if isinstance(job.request_json, dict) else {}
    prompt = params.get("prompt")
    return prompt if isinstance(prompt, str) else None


def _duration_seconds_of(job: GenerationJob) -> int | None:
    params = job.request_json if isinstance(job.request_json, dict) else {}
    duration = params.get("duration_seconds")
    return duration if isinstance(duration, int) else None


def _first_reference_asset_id(job: GenerationJob) -> str | None:
    # Signing costs a request to the storage backend, so this stays scoped to
    # the one operation that actually needs its input echoed back — every
    # other operation's client already knows its own reference (it just
    # uploaded it) and has no use for this field.
    if job.operation != Operation.VIDEO_ANALYSIS.value:
        return None
    params = job.request_json if isinstance(job.request_json, dict) else {}
    references = params.get("reference_asset_ids")
    if not isinstance(references, list) or not references:
        return None
    return references[0] if isinstance(references[0], str) else None


def _reference_url_of(session: Session, job: GenerationJob) -> str | None:
    reference_id = _first_reference_asset_id(job)
    return media_urls.asset_url(session, reference_id) if reference_id else None


def _analysis_of(job: GenerationJob) -> VideoAnalysisResult | None:
    raw = job.analysis_result_json
    if not isinstance(raw, dict):
        return None
    try:
        return VideoAnalysisResult.model_validate(raw)
    except ValueError:
        # A malformed/legacy payload must not break the whole job response —
        # the client just shows no structured result for it.
        return None


def _asset_kind_of(job: GenerationJob) -> ImageAssetKind | None:
    params = job.request_json if isinstance(job.request_json, dict) else {}
    raw = params.get("asset_kind")
    try:
        return ImageAssetKind(raw) if raw else None
    except ValueError:
        return None


def _video_asset_kind_of(job: GenerationJob) -> VideoAssetKind | None:
    params = job.request_json if isinstance(job.request_json, dict) else {}
    raw = params.get("video_asset_kind")
    try:
        return VideoAssetKind(raw) if raw else None
    except ValueError:
        return None


def _forced_model_of(job: GenerationJob) -> str | None:
    params = job.request_json if isinstance(job.request_json, dict) else {}
    raw = params.get("forced_model")
    return raw if isinstance(raw, str) and raw else None


def _character_views_of(job: GenerationJob) -> list[CharacterViewAngle] | None:
    params = job.request_json if isinstance(job.request_json, dict) else {}
    raw = params.get("character_views")
    if not isinstance(raw, list) or not raw:
        return None
    try:
        return [CharacterViewAngle(value) for value in raw]
    except ValueError:
        return None
