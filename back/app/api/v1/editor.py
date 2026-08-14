"""Drama series, episode cuts, revisions, leases, plans, variants and exports."""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import StreamingResponse

from app.api.deps import CurrentUser, DbSession, IdempotencyKey, rate_limited
from app.api.schemas.editor import (
    ApplyCommandsRequest,
    BindEditorExportRequest,
    CutCreateRequest,
    CutFromJobRequest,
    CutRevisionResponse,
    DeliveryVariantResponse,
    DramaEpisodeCreateRequest,
    DramaEpisodeResponse,
    DramaSeriesCreateRequest,
    DramaSeriesResponse,
    EditorExportResponse,
    EditorOperationResponse,
    EditPlanApplyRequest,
    EditPlanCreateRequest,
    EditPlanResponse,
    EpisodeCutResponse,
    ExportClaimRequest,
    ExportCompleteRequest,
    ExportFailRequest,
    ExportHeartbeatRequest,
    ExportQueueRequest,
    ExportUploadRequest,
    LeaseAcquireRequest,
    LeaseResponse,
    McpTokenCreateRequest,
    McpTokenResponse,
    TimelineSummaryResponse,
    VariantBatchCreateRequest,
)
from app.api.schemas.jobs import UploadPresignResponse
from app.domain.editor import analysis as media_analysis
from app.domain.editor import document as docs
from app.domain.editor import exports as export_service
from app.domain.editor import flags as editor_flags
from app.domain.editor import leases as lease_service
from app.domain.editor import service as editor_service
from app.domain.errors import NotFound, ValidationFailed
from app.models import CutRevision, DeliveryVariant, EditorExport, EditPlan, EpisodeCut
from app.models.enums import EditorExportStatus, EditPlanStatus, MediaAnalysisStatus
from app.presenters.media_urls import asset_url
from app.realtime import publisher
from app.workers.celery_app import celery_app

router = APIRouter(tags=["editor"])
SSE_HEARTBEAT_SECONDS = 15
SSE_MAX_DURATION_SECONDS = 600


def _operation_status_is_terminal(status: str) -> bool:
    for enum_cls in (EditorExportStatus, EditPlanStatus, MediaAnalysisStatus):
        try:
            return bool(enum_cls(status).is_terminal)
        except ValueError:
            continue
    return False


def _series_response(series) -> DramaSeriesResponse:  # type: ignore[no-untyped-def]
    return DramaSeriesResponse(
        id=series.id,
        title=series.title,
        description=series.description,
        kind=series.kind,
        default_locale=series.default_locale,
        status=series.status,
        allow_external_models=series.allow_external_models,
        shortform_profile_key=series.shortform_profile_key,
        created_at=series.created_at,
    )


def _episode_response(episode) -> DramaEpisodeResponse:  # type: ignore[no-untyped-def]
    return DramaEpisodeResponse(
        id=episode.id,
        series_id=episode.series_id,
        episode_number=episode.episode_number,
        title=episode.title,
        synopsis=episode.synopsis,
        status=episode.status,
        canonical_work_id=episode.canonical_work_id,
    )


def _revision_asset_urls(session, revision: CutRevision) -> dict[str, str]:  # type: ignore[no-untyped-def]
    asset_ids = {
        str(binding.get("asset_id"))
        for binding in revision.asset_bindings_json or []
        if binding.get("asset_id")
    }
    overlay = (revision.document_json or {}).get("brand_overlay") or {}
    if overlay.get("asset_id"):
        asset_ids.add(str(overlay["asset_id"]))
    urls: dict[str, str] = {}
    for asset_id in asset_ids:
        url = asset_url(session, asset_id)
        if url:
            urls[asset_id] = url
    return urls


def _revision_response(session, revision: CutRevision) -> CutRevisionResponse:  # type: ignore[no-untyped-def]
    return CutRevisionResponse(
        id=revision.id,
        cut_id=revision.cut_id,
        revision_no=revision.revision_no,
        parent_revision_id=revision.parent_revision_id,
        duration_ticks=revision.duration_ticks,
        content_hash=revision.content_hash,
        summary=TimelineSummaryResponse.model_validate(
            docs.timeline_summary(revision.document_json)
        ),
        document=dict(revision.document_json),
        asset_urls=_revision_asset_urls(session, revision),
        created_at=revision.created_at,
    )


def _cut_response(session, cut: EpisodeCut) -> EpisodeCutResponse:  # type: ignore[no-untyped-def]
    head = editor_service.head_revision(session, cut)
    active = lease_service.peek_active(session, cut.id)
    return EpisodeCutResponse(
        id=cut.id,
        episode_id=cut.episode_id,
        kind=cut.kind,
        name=cut.name,
        status=cut.status,
        head_revision_id=cut.head_revision_id,
        source_asset_id=cut.source_asset_id,
        source_job_id=cut.source_job_id,
        source_url=asset_url(session, cut.source_asset_id),
        lease_held=active is not None,
        head=_revision_response(session, head) if head else None,
    )


def _plan_response(plan: EditPlan) -> EditPlanResponse:
    return EditPlanResponse(
        id=plan.id,
        cut_id=plan.cut_id,
        base_revision_id=plan.base_revision_id,
        status=plan.status,
        summary=plan.summary,
        commands=list(plan.commands_json),
        diff=dict(plan.diff_json),
        warnings=list(plan.warnings_json),
        applied_revision_id=plan.applied_revision_id,
        expires_at=plan.expires_at,
    )


def _variant_response(variant: DeliveryVariant) -> DeliveryVariantResponse:
    return DeliveryVariantResponse(
        id=variant.id,
        cut_revision_id=variant.cut_revision_id,
        profile_key=variant.profile_key,
        width=variant.width,
        height=variant.height,
        format=variant.format,
        spec_hash=variant.spec_hash,
        status=variant.status,
    )


def _export_response(export: EditorExport) -> EditorExportResponse:
    return EditorExportResponse(
        id=export.id,
        variant_id=export.variant_id,
        status=export.status,
        operation_key=export.operation_key,
        attempt=export.attempt,
        progress=export.progress,
        output_asset_id=export.output_asset_id,
        failure_code=export.failure_code,
        failure_message=export.failure_message,
    )


@router.post("/drama-series", response_model=DramaSeriesResponse, status_code=201)
def create_drama_series(
    payload: DramaSeriesCreateRequest,
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("editor_write"))],
    _idem: IdempotencyKey,
) -> DramaSeriesResponse:
    series = editor_service.create_drama_series(
        session,
        user_id=user.id,
        title=payload.title,
        description=payload.description,
        default_locale=payload.default_locale,
        shortform_profile_key=payload.shortform_profile_key,
        allow_external_models=payload.allow_external_models,
    )
    session.commit()
    return _series_response(series)


@router.get("/drama-series", response_model=list[DramaSeriesResponse])
def list_drama_series(user: CurrentUser, session: DbSession) -> list[DramaSeriesResponse]:
    rows = editor_service.list_drama_series(session, user_id=user.id)
    return [_series_response(item) for item in rows]


@router.get("/drama-series/{series_id}", response_model=DramaSeriesResponse)
def get_drama_series(series_id: str, user: CurrentUser, session: DbSession) -> DramaSeriesResponse:
    series = editor_service.require_drama_series(session, user_id=user.id, series_id=series_id)
    return _series_response(series)


@router.post(
    "/drama-series/{series_id}/episodes", response_model=DramaEpisodeResponse, status_code=201
)
def create_episode(
    series_id: str,
    payload: DramaEpisodeCreateRequest,
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("editor_write"))],
) -> DramaEpisodeResponse:
    episode = editor_service.create_episode(
        session,
        user_id=user.id,
        series_id=series_id,
        title=payload.title,
        episode_number=payload.episode_number,
        synopsis=payload.synopsis,
    )
    session.commit()
    return _episode_response(episode)


@router.get("/drama-series/{series_id}/episodes", response_model=list[DramaEpisodeResponse])
def list_episodes(
    series_id: str, user: CurrentUser, session: DbSession
) -> list[DramaEpisodeResponse]:
    return [
        _episode_response(item)
        for item in editor_service.list_episodes(session, user_id=user.id, series_id=series_id)
    ]


@router.post("/episode-cuts:from-job", response_model=EpisodeCutResponse, status_code=201)
def create_cut_from_job(
    payload: CutFromJobRequest,
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("editor_write"))],
) -> EpisodeCutResponse:
    cut, _revision = editor_service.create_cut_from_job(
        session,
        user_id=user.id,
        job_id=payload.job_id,
        series_id=payload.series_id,
        title=payload.title,
    )
    if cut.source_asset_id:
        analysis = media_analysis.enqueue(session, asset_id=cut.source_asset_id)
        celery_app.send_task("app.workers.tasks.run_media_analysis", args=[analysis.id])
    session.commit()
    return _cut_response(session, cut)


@router.post(
    "/drama-episodes/{episode_id}/cuts",
    response_model=EpisodeCutResponse,
    status_code=201,
)
def create_cut(
    episode_id: str,
    payload: CutCreateRequest,
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("editor_write"))],
) -> EpisodeCutResponse:
    cut, _revision = editor_service.create_cut_from_asset(
        session,
        user_id=user.id,
        episode_id=episode_id,
        asset_id=payload.asset_id,
        name=payload.name,
        kind=payload.kind,
        job_id=payload.job_id,
    )
    if cut.source_asset_id:
        analysis = media_analysis.enqueue(session, asset_id=cut.source_asset_id)
        celery_app.send_task("app.workers.tasks.run_media_analysis", args=[analysis.id])
    session.commit()
    return _cut_response(session, cut)


@router.get("/drama-episodes/{episode_id}/cuts", response_model=list[EpisodeCutResponse])
def list_cuts(episode_id: str, user: CurrentUser, session: DbSession) -> list[EpisodeCutResponse]:
    return [
        _cut_response(session, item)
        for item in editor_service.list_cuts(session, user_id=user.id, episode_id=episode_id)
    ]


@router.get("/episode-cuts/{cut_id}", response_model=EpisodeCutResponse)
def get_cut(cut_id: str, user: CurrentUser, session: DbSession) -> EpisodeCutResponse:
    editor_flags.require_flag(session, editor_flags.FLAG_EDITOR, user_id=user.id)
    cut = editor_service._owned_cut(session, user_id=user.id, cut_id=cut_id)
    return _cut_response(session, cut)


@router.post("/episode-cuts/{cut_id}/leases", response_model=LeaseResponse, status_code=201)
def acquire_lease(
    cut_id: str,
    payload: LeaseAcquireRequest,
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("editor_write"))],
) -> LeaseResponse:
    lease, token = editor_service.acquire_lease(
        session, user_id=user.id, cut_id=cut_id, browser_instance_id=payload.browser_instance_id
    )
    session.commit()
    return LeaseResponse(
        id=lease.id,
        cut_id=lease.cut_id,
        expires_at=lease.expires_at,
        token=token or None,
        base_revision_id=lease.base_revision_id,
    )


@router.post("/episode-cuts/{cut_id}/leases/{lease_id}/heartbeat", response_model=LeaseResponse)
def heartbeat_lease(
    cut_id: str,
    lease_id: str,
    payload: LeaseAcquireRequest,
    user: CurrentUser,
    session: DbSession,
    lease_token: Annotated[str | None, Header(alias="X-Editor-Lease-Token")] = None,
) -> LeaseResponse:
    if not lease_token:
        raise ValidationFailed("缺少编辑租约令牌。")
    lease = lease_service.require_write_lease(
        session, cut_id=cut_id, user_id=user.id, lease_id=lease_id, token=lease_token
    )
    if lease.browser_instance_id != payload.browser_instance_id:
        raise ValidationFailed("租约不属于该浏览器实例。")
    lease = lease_service.heartbeat(session, lease=lease)
    session.commit()
    return LeaseResponse(
        id=lease.id,
        cut_id=lease.cut_id,
        expires_at=lease.expires_at,
        base_revision_id=lease.base_revision_id,
    )


@router.delete("/episode-cuts/{cut_id}/leases/{lease_id}", status_code=204)
def release_lease(
    cut_id: str,
    lease_id: str,
    user: CurrentUser,
    session: DbSession,
    lease_token: Annotated[str | None, Header(alias="X-Editor-Lease-Token")] = None,
) -> None:
    if not lease_token:
        raise ValidationFailed("缺少编辑租约令牌。")
    lease = lease_service.require_write_lease(
        session, cut_id=cut_id, user_id=user.id, lease_id=lease_id, token=lease_token
    )
    lease_service.release(session, lease=lease)
    session.commit()


@router.post(
    "/episode-cuts/{cut_id}/revisions",
    response_model=CutRevisionResponse,
    status_code=201,
)
def apply_revision(
    cut_id: str,
    payload: ApplyCommandsRequest,
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("editor_write"))],
) -> CutRevisionResponse:
    revision = editor_service.apply_commands(
        session,
        user_id=user.id,
        cut_id=cut_id,
        lease_id=payload.lease_id,
        lease_token=payload.lease_token,
        payload=payload.model_dump(),
    )
    session.commit()
    return _revision_response(session, revision)


@router.post("/episode-cuts/{cut_id}/edit-plans", response_model=EditPlanResponse, status_code=202)
def create_edit_plan(
    cut_id: str,
    payload: EditPlanCreateRequest,
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("editor_write"))],
) -> EditPlanResponse:
    from app.agents import editor_planner

    editor_flags.require_flag(session, editor_flags.FLAG_AI, user_id=user.id)
    cut = editor_service._owned_cut(session, user_id=user.id, cut_id=cut_id)
    head = editor_service.head_revision(session, cut)
    if head is None:
        raise ValidationFailed("剪辑还没有可编辑的修订。")
    outcome = editor_planner.plan_timeline(
        session,
        user_id=user.id,
        cut=cut,
        revision=head,
        goal=payload.goal,
        max_commands=payload.max_commands,
    )
    plan = editor_service.create_edit_plan(
        session,
        user_id=user.id,
        cut_id=cut_id,
        goal=payload.goal,
        commands=list(outcome.data.get("commands") or []),
        summary=str(outcome.data.get("summary") or payload.goal),
        agent_run_id=outcome.agent_run_id,
        model=outcome.model,
        warnings=[str(item) for item in (outcome.data.get("warnings") or [])],
    )
    session.commit()
    return _plan_response(plan)


@router.post("/edit-plans/{plan_id}/apply", response_model=CutRevisionResponse)
def apply_edit_plan(
    plan_id: str,
    payload: EditPlanApplyRequest,
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("editor_write"))],
) -> CutRevisionResponse:
    revision = editor_service.apply_edit_plan(
        session,
        user_id=user.id,
        plan_id=plan_id,
        lease_id=payload.lease_id,
        lease_token=payload.lease_token,
        selected_indexes=payload.selected_indexes,
    )
    session.commit()
    return _revision_response(session, revision)


@router.post("/edit-plans/{plan_id}/reject", response_model=EditPlanResponse)
def reject_edit_plan(plan_id: str, user: CurrentUser, session: DbSession) -> EditPlanResponse:
    plan = editor_service.reject_edit_plan(session, user_id=user.id, plan_id=plan_id)
    session.commit()
    return _plan_response(plan)


@router.post(
    "/cut-revisions/{revision_id}/delivery-variants:batchCreate",
    response_model=list[DeliveryVariantResponse],
    status_code=201,
)
def batch_create_variants(
    revision_id: str,
    payload: VariantBatchCreateRequest,
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("editor_write"))],
) -> list[DeliveryVariantResponse]:
    variants = editor_service.create_variants(
        session,
        user_id=user.id,
        revision_id=revision_id,
        profile_keys=payload.profile_keys,
        caption_language=payload.caption_language,
        caption_mode=payload.caption_mode,
        format=payload.format,
    )
    session.commit()
    return [_variant_response(item) for item in variants]


@router.post("/editor-exports:claim", response_model=EditorExportResponse)
def claim_export(
    payload: ExportClaimRequest,
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("editor_export"))],
) -> EditorExportResponse:
    export = export_service.claim_next(
        session,
        user_id=user.id,
        runner_instance_id=payload.runner_instance_id,
        capabilities={
            "chrome_or_edge": payload.chrome_or_edge,
            "webcodecs": payload.webcodecs,
            "webgpu": payload.webgpu,
        },
    )
    if export is None:
        raise NotFound("没有可认领的导出任务。")
    session.commit()
    return _export_response(export)


@router.post("/editor-exports", response_model=list[EditorExportResponse], status_code=202)
def queue_exports(
    payload: ExportQueueRequest,
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("editor_export"))],
) -> list[EditorExportResponse]:
    exports = export_service.queue_exports(
        session,
        user_id=user.id,
        variant_ids=payload.variant_ids,
        operation_key=payload.operation_key,
    )
    session.commit()
    return [_export_response(item) for item in exports]


@router.post("/editor-exports/{export_id}/heartbeat", response_model=EditorExportResponse)
def export_heartbeat(
    export_id: str,
    payload: ExportHeartbeatRequest,
    user: CurrentUser,
    session: DbSession,
) -> EditorExportResponse:
    export = export_service.heartbeat(
        session,
        user_id=user.id,
        export_id=export_id,
        progress=payload.progress,
        stage=payload.stage,
    )
    session.commit()
    return _export_response(export)


@router.post("/editor-exports/{export_id}/upload-session", response_model=UploadPresignResponse)
def export_upload_session(
    export_id: str,
    payload: ExportUploadRequest,
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("editor_export"))],
) -> UploadPresignResponse:
    presigned = export_service.presign_export_upload(
        session,
        user_id=user.id,
        export_id=export_id,
        filename=payload.filename,
        mime_type=payload.mime_type,
        size_bytes=payload.size_bytes,
        checksum_sha256=payload.checksum_sha256,
    )
    session.commit()
    return UploadPresignResponse(
        upload_session_id=presigned.upload_session.id,
        upload_url=presigned.upload_url,
        object_key=presigned.upload_session.object_key,
        expires_at=presigned.upload_session.expires_at,
        required_headers=presigned.required_headers,
    )


@router.post("/editor-exports/{export_id}/complete", response_model=EditorExportResponse)
def complete_export(
    export_id: str,
    payload: ExportCompleteRequest,
    user: CurrentUser,
    session: DbSession,
) -> EditorExportResponse:
    export = export_service.complete_export(
        session, user_id=user.id, export_id=export_id, upload_session_id=payload.upload_session_id
    )
    session.commit()
    return _export_response(export)


@router.post("/editor-exports/{export_id}/fail", response_model=EditorExportResponse)
def fail_export(
    export_id: str,
    payload: ExportFailRequest,
    user: CurrentUser,
    session: DbSession,
) -> EditorExportResponse:
    export = export_service.fail_export(
        session, user_id=user.id, export_id=export_id, code=payload.code, message=payload.message
    )
    session.commit()
    return _export_response(export)


@router.post("/editor-exports/{export_id}/cancel", response_model=EditorExportResponse)
def cancel_export(export_id: str, user: CurrentUser, session: DbSession) -> EditorExportResponse:
    export = export_service.request_cancel(session, user_id=user.id, export_id=export_id)
    session.commit()
    return _export_response(export)


@router.post(
    "/editor-exports/{export_id}/retry",
    response_model=EditorExportResponse,
    status_code=202,
)
def retry_export(export_id: str, user: CurrentUser, session: DbSession) -> EditorExportResponse:
    export = export_service.retry_export(session, user_id=user.id, export_id=export_id)
    session.commit()
    return _export_response(export)


@router.post("/drafts/{draft_id}/bind-editor-export", response_model=dict[str, str])
def bind_editor_export(
    draft_id: str,
    payload: BindEditorExportRequest,
    user: CurrentUser,
    session: DbSession,
) -> dict[str, str]:
    draft = export_service.bind_draft_export(
        session,
        user_id=user.id,
        draft_id=draft_id,
        export_id=payload.export_id,
        confirmed=payload.confirmed,
    )
    session.commit()
    return {"draft_id": draft.id, "export_id": payload.export_id}


@router.get("/editor-operations/{operation_id}", response_model=EditorOperationResponse)
def get_operation(
    operation_id: str, user: CurrentUser, session: DbSession
) -> EditorOperationResponse:
    editor_flags.require_flag(session, editor_flags.FLAG_EDITOR, user_id=user.id)
    if operation_id.startswith("exp_"):
        export = session.get(EditorExport, operation_id)
        if export is None:
            raise NotFound("操作不存在。")
        return EditorOperationResponse(
            id=export.id,
            kind="export",
            status=export.status,
            progress=export.progress,
            result={"output_asset_id": export.output_asset_id},
            error={"code": export.failure_code} if export.failure_code else None,
        )
    if operation_id.startswith("epl_"):
        plan = session.get(EditPlan, operation_id)
        if plan is None:
            raise NotFound("操作不存在。")
        return EditorOperationResponse(
            id=plan.id,
            kind="edit_plan",
            status=plan.status,
            progress=100 if plan.commands_json else 10,
        )
    if operation_id.startswith("man_"):
        from app.models import MediaAnalysis

        analysis = session.get(MediaAnalysis, operation_id)
        if analysis is None:
            raise NotFound("操作不存在。")
        return EditorOperationResponse(
            id=analysis.id,
            kind="media_analysis",
            status=analysis.status,
            progress=100 if analysis.status in {"succeeded", "degraded", "failed"} else 10,
        )
    raise NotFound("操作不存在。")


@router.get("/editor-operations/{operation_id}/events")
def stream_operation_events(
    operation_id: str,
    request: Request,
    user: CurrentUser,
    session: DbSession,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> StreamingResponse:
    editor_flags.require_flag(session, editor_flags.FLAG_EDITOR, user_id=user.id)
    after = 0
    if last_event_id:
        try:
            after = int(last_event_id)
        except ValueError:
            after = 0
    backfill = [
        {
            "sequence": event.sequence,
            "event_type": event.event_type,
            "status": event.status,
            "progress": event.progress,
            "message": event.public_message,
        }
        for event in editor_service.events_since(session, operation_id, after)
    ]

    def events() -> Iterator[str]:
        started = time.monotonic()
        last_sequence = after
        for item in backfill:
            sequence_value = item["sequence"]
            last_sequence = (
                sequence_value if isinstance(sequence_value, int) else int(str(sequence_value))
            )
            yield _sse(item)
        if backfill and _operation_status_is_terminal(str(backfill[-1]["status"])):
            return
        last_heartbeat = time.monotonic()
        for payload in publisher.subscribe(operation_id):
            if time.monotonic() - started > SSE_MAX_DURATION_SECONDS:
                break
            if not payload:
                if time.monotonic() - last_heartbeat > SSE_HEARTBEAT_SECONDS:
                    last_heartbeat = time.monotonic()
                    yield ": keepalive\n\n"
                continue
            sequence = int(payload.get("sequence", 0))
            if sequence <= last_sequence:
                continue
            last_sequence = sequence
            yield _sse(payload)
            if _operation_status_is_terminal(str(payload.get("status") or "")):
                return

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "cache-control": "no-cache",
            "connection": "keep-alive",
            "x-accel-buffering": "no",
        },
    )


@router.post("/mcp/tokens", response_model=McpTokenResponse, status_code=201)
def create_mcp_token(
    payload: McpTokenCreateRequest,
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("authenticated_write"))],
) -> McpTokenResponse:
    from app.mcp import auth as mcp_auth

    grant, token, expires_at = mcp_auth.issue_grant(
        session,
        user_id=user.id,
        series_id=payload.series_id,
        client_id=payload.client_id,
        scopes=payload.scopes,
    )
    session.commit()
    return McpTokenResponse(
        access_token=token,
        expires_at=expires_at,
        grant_id=grant.id,
        scopes=list(grant.scopes_json),
        project_id=grant.series_id,
    )


@router.delete("/mcp/tokens/{grant_id}", status_code=204)
def revoke_mcp_token(grant_id: str, user: CurrentUser, session: DbSession) -> None:
    from app.mcp import auth as mcp_auth

    mcp_auth.revoke_grant(session, user_id=user.id, grant_id=grant_id)
    session.commit()


def _sse(payload: dict[str, Any]) -> str:
    return f"id: {payload['sequence']}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
