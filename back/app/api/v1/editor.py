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
    CollaborationInviteResponse,
    CollaboratorInviteRequest,
    CollaboratorResponse,
    CutCreateRequest,
    CutFromJobRequest,
    CutRevisionResponse,
    CutRevisionSummaryResponse,
    DeliveryVariantResponse,
    DramaEpisodeCreateRequest,
    DramaEpisodeResponse,
    DramaEpisodeUpdateRequest,
    DramaSeriesCreateRequest,
    DramaSeriesResponse,
    DramaSeriesUpdateRequest,
    EditorExportResponse,
    EditorOperationResponse,
    EditPlanApplyRequest,
    EditPlanCreateRequest,
    EditPlanResponse,
    EpisodeContentLinkCreateRequest,
    EpisodeContentLinkResponse,
    EpisodeCutResponse,
    EpisodeExportResponse,
    EpisodeSetCanonicalWorkRequest,
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
    RevisionRestoreRequest,
    TimelineSummaryResponse,
    VariantBatchCreateRequest,
)
from app.api.schemas.jobs import UploadPresignResponse
from app.api.schemas.works import AuthorSummary
from app.domain.editor import analysis as media_analysis
from app.domain.editor import collaborators
from app.domain.editor import document as docs
from app.domain.editor import exports as export_service
from app.domain.editor import flags as editor_flags
from app.domain.editor import leases as lease_service
from app.domain.editor import service as editor_service
from app.domain.errors import NotFound, ValidationFailed
from app.models import (
    Asset,
    CutRevision,
    DeliveryVariant,
    EditorExport,
    EditPlan,
    EpisodeCut,
    MediaAnalysis,
    Profile,
    Series,
    SeriesCollaborator,
)
from app.models.enums import EditorExportStatus, EditPlanStatus, MediaAnalysisStatus
from app.presenters.media_urls import asset_url
from app.realtime import publisher
from app.workers.celery_app import celery_app

router = APIRouter(tags=["editor"])
SSE_HEARTBEAT_SECONDS = 15
SSE_MAX_DURATION_SECONDS = 600


def _queue_analysis_if_needed(session: Any, asset_id: str | None) -> str | None:
    if not asset_id:
        return None
    return media_analysis.enqueue(session, asset_id=asset_id).id


def _enqueue_media_analysis(analysis_id: str) -> None:
    celery_app.send_task("app.workers.tasks.run_media_analysis", args=[analysis_id])


def _operation_status_is_terminal(status: str) -> bool:
    for enum_cls in (EditorExportStatus, EditPlanStatus, MediaAnalysisStatus):
        try:
            return bool(enum_cls(status).is_terminal)
        except ValueError:
            continue
    return False


def _author_summary(
    session: DbSession, user_id: str, profile: Profile | None = None
) -> AuthorSummary:
    if profile is None:
        profile = collaborators.profiles_by_user_id(session, [user_id]).get(user_id)
    if profile is None:
        return AuthorSummary(user_id=user_id, display_name="未知作者", handle=user_id)
    return AuthorSummary(
        user_id=user_id,
        display_name=profile.display_name,
        handle=profile.handle,
        avatar_url=asset_url(session, profile.avatar_asset_id),
    )


def _series_response(
    session: DbSession,
    series: Series,
    stats: dict[str, int] | None = None,
    *,
    viewer_user_id: str | None = None,
    owner_profile: Profile | None = None,
    collaborator_count: int | None = None,
) -> DramaSeriesResponse:
    counts = stats or {}
    if collaborator_count is None:
        collaborator_count = len(collaborators.active_members(session, series_id=series.id))
    viewer_role = (
        "owner"
        if viewer_user_id is None or viewer_user_id == series.owner_user_id
        else "collaborator"
    )
    return DramaSeriesResponse(
        id=series.id,
        title=series.title,
        description=series.description,
        kind=series.kind,
        default_locale=series.default_locale,
        status=series.status,
        allow_external_models=series.allow_external_models,
        shortform_profile_key=series.shortform_profile_key,
        english_title=series.english_title,
        planned_episode_count=series.planned_episode_count,
        genre_tags=list(series.genre_tags_json or []),
        target_platforms=list(series.target_platforms_json or []),
        logo_asset_id=series.logo_asset_id,
        logo_url=asset_url(session, series.logo_asset_id),
        episode_count=counts.get("episode_count", 0),
        script_count=counts.get("script_count", 0),
        video_count=counts.get("video_count", 0),
        published_count=counts.get("published_count", 0),
        created_at=series.created_at,
        updated_at=series.updated_at,
        owner=_author_summary(session, series.owner_user_id, owner_profile),
        viewer_role=viewer_role,
        is_collaboration=collaborator_count > 0,
        collaborator_count=collaborator_count,
    )


def _collaborator_response(session: DbSession, row: SeriesCollaborator) -> CollaboratorResponse:
    profile = collaborators.profiles_by_user_id(session, [row.user_id]).get(row.user_id)
    return CollaboratorResponse(
        id=row.id,
        user_id=row.user_id,
        handle=profile.handle if profile else row.user_id,
        display_name=profile.display_name if profile else "未知用户",
        avatar_url=asset_url(session, profile.avatar_asset_id) if profile else None,
        status=row.status,
        invited_by_user_id=row.invited_by_user_id,
        created_at=row.created_at,
        responded_at=row.responded_at,
    )


def episode_response(episode, *, has_script_turns: bool = False) -> DramaEpisodeResponse:  # type: ignore[no-untyped-def]
    return DramaEpisodeResponse(
        id=episode.id,
        series_id=episode.series_id,
        season_number=episode.season_number,
        episode_number=episode.episode_number,
        episode_kind=episode.episode_kind,
        title=episode.title,
        synopsis=episode.synopsis,
        status=episode.status,
        canonical_work_id=episode.canonical_work_id,
        has_script_turns=has_script_turns,
    )


def content_link_response(link) -> EpisodeContentLinkResponse:  # type: ignore[no-untyped-def]
    return EpisodeContentLinkResponse(
        id=link.id,
        episode_id=link.episode_id,
        content_type=link.content_type,
        content_ref_id=link.content_ref_id,
        role=link.role,
        created_at=link.created_at,
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
    # Revisions are immutable snapshots, so a revision persisted before a
    # field like `markers` existed never gets rewritten — `canonicalize()`
    # backfills it transparently here at serving time (same read-time
    # upgrade path as `_normalize_track`), rather than serving the raw,
    # possibly-missing-field dict straight from storage.
    document = docs.canonicalize(revision.document_json)
    return CutRevisionResponse(
        id=revision.id,
        cut_id=revision.cut_id,
        revision_no=revision.revision_no,
        parent_revision_id=revision.parent_revision_id,
        duration_ticks=revision.duration_ticks,
        content_hash=revision.content_hash,
        summary=TimelineSummaryResponse.model_validate(docs.timeline_summary(document)),
        document=document,
        asset_urls=_revision_asset_urls(session, revision),
        created_at=revision.created_at,
    )


def _revision_summary_response(
    revision: CutRevision, *, head_revision_id: str | None
) -> CutRevisionSummaryResponse:
    return CutRevisionSummaryResponse(
        id=revision.id,
        cut_id=revision.cut_id,
        revision_no=revision.revision_no,
        parent_revision_id=revision.parent_revision_id,
        duration_ticks=revision.duration_ticks,
        is_head=revision.id == head_revision_id,
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
        english_title=payload.english_title,
        planned_episode_count=payload.planned_episode_count,
        genre_tags=payload.genre_tags,
        target_platforms=payload.target_platforms,
        logo_asset_id=payload.logo_asset_id,
    )
    session.commit()
    return _series_response(session, series, viewer_user_id=user.id)


@router.get("/drama-series", response_model=list[DramaSeriesResponse])
def list_drama_series(
    user: CurrentUser,
    session: DbSession,
    q: str | None = None,
    genre: str | None = None,
    sort: str = "updated_at",
    sort_dir: str = "desc",
    status: str | None = None,
) -> list[DramaSeriesResponse]:
    rows = editor_service.list_drama_series(
        session, user_id=user.id, q=q, genre=genre, sort=sort, sort_dir=sort_dir, status=status
    )
    stats = editor_service.series_stats(session, series_ids=[item.id for item in rows])
    owner_profiles = collaborators.profiles_by_user_id(
        session, [item.owner_user_id for item in rows]
    )
    collab_counts = collaborators.active_member_counts(
        session, series_ids=[item.id for item in rows]
    )
    return [
        _series_response(
            session,
            item,
            stats.get(item.id),
            viewer_user_id=user.id,
            owner_profile=owner_profiles.get(item.owner_user_id),
            collaborator_count=collab_counts.get(item.id, 0),
        )
        for item in rows
    ]


@router.get("/drama-series/{series_id}", response_model=DramaSeriesResponse)
def get_drama_series(series_id: str, user: CurrentUser, session: DbSession) -> DramaSeriesResponse:
    series = editor_service.require_accessible_drama_series(
        session, user_id=user.id, series_id=series_id
    )
    stats = editor_service.series_stats(session, series_ids=[series.id])
    return _series_response(session, series, stats.get(series.id), viewer_user_id=user.id)


@router.patch("/drama-series/{series_id}", response_model=DramaSeriesResponse)
def update_drama_series(
    series_id: str,
    payload: DramaSeriesUpdateRequest,
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("editor_write"))],
) -> DramaSeriesResponse:
    series = editor_service.update_drama_series(
        session,
        user_id=user.id,
        series_id=series_id,
        title=payload.title,
        description=payload.description,
        english_title=payload.english_title,
        planned_episode_count=payload.planned_episode_count,
        genre_tags=payload.genre_tags,
        target_platforms=payload.target_platforms,
        logo_asset_id=payload.logo_asset_id,
    )
    session.commit()
    stats = editor_service.series_stats(session, series_ids=[series.id])
    return _series_response(session, series, stats.get(series.id), viewer_user_id=user.id)


@router.delete("/drama-series/{series_id}", status_code=204)
def trash_drama_series(
    series_id: str,
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("editor_write"))],
) -> None:
    editor_service.trash_drama_series(session, user_id=user.id, series_id=series_id)
    session.commit()


@router.post("/drama-series/{series_id}/untrash", response_model=DramaSeriesResponse)
def untrash_drama_series(
    series_id: str,
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("editor_write"))],
) -> DramaSeriesResponse:
    series = editor_service.untrash_drama_series(session, user_id=user.id, series_id=series_id)
    session.commit()
    stats = editor_service.series_stats(session, series_ids=[series.id])
    return _series_response(session, series, stats.get(series.id), viewer_user_id=user.id)


@router.delete("/drama-series/{series_id}/purge", status_code=204)
def purge_drama_series(
    series_id: str,
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("editor_write"))],
) -> None:
    editor_service.purge_drama_series(session, user_id=user.id, series_id=series_id)
    session.commit()


@router.post(
    "/drama-series/{series_id}/collaborators",
    response_model=CollaboratorResponse,
    status_code=201,
)
def invite_collaborator(
    series_id: str,
    payload: CollaboratorInviteRequest,
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("series_collab_invite"))],
) -> CollaboratorResponse:
    row = collaborators.invite(
        session, owner_user_id=user.id, series_id=series_id, identifier=payload.identifier
    )
    session.commit()
    return _collaborator_response(session, row)


@router.get(
    "/drama-series/{series_id}/collaborators",
    response_model=list[CollaboratorResponse],
)
def list_collaborators(
    series_id: str,
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("public_read"))],
) -> list[CollaboratorResponse]:
    rows = collaborators.list_members(session, user_id=user.id, series_id=series_id)
    return [_collaborator_response(session, item) for item in rows]


@router.delete(
    "/drama-series/{series_id}/collaborators/{collaborator_id}",
    status_code=204,
)
def remove_collaborator(
    series_id: str,
    collaborator_id: str,
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("editor_write"))],
) -> None:
    collaborators.remove(
        session, actor_user_id=user.id, series_id=series_id, collaborator_id=collaborator_id
    )
    session.commit()


@router.get("/collaboration-invites", response_model=list[CollaborationInviteResponse])
def list_collaboration_invites(
    user: CurrentUser, session: DbSession
) -> list[CollaborationInviteResponse]:
    rows = collaborators.list_my_invites(session, user_id=user.id)
    series_by_id = {
        series.id: series
        for series in (
            session.get(Series, row.series_id)
            for row in rows
        )
        if series is not None
    }
    inviter_profiles = collaborators.profiles_by_user_id(
        session, [row.invited_by_user_id for row in rows]
    )
    results: list[CollaborationInviteResponse] = []
    for row in rows:
        series = series_by_id.get(row.series_id)
        if series is None:
            continue
        results.append(
            CollaborationInviteResponse(
                id=row.id,
                series_id=series.id,
                series_title=series.title,
                series_logo_url=asset_url(session, series.logo_asset_id),
                inviter=_author_summary(
                    session, row.invited_by_user_id, inviter_profiles.get(row.invited_by_user_id)
                ),
                created_at=row.created_at,
            )
        )
    return results


@router.post(
    "/collaboration-invites/{collaborator_id}/accept",
    response_model=CollaboratorResponse,
)
def accept_collaboration_invite(
    collaborator_id: str,
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("editor_write"))],
) -> CollaboratorResponse:
    row = collaborators.accept(session, user_id=user.id, collaborator_id=collaborator_id)
    session.commit()
    return _collaborator_response(session, row)


@router.post(
    "/collaboration-invites/{collaborator_id}/decline",
    response_model=CollaboratorResponse,
)
def decline_collaboration_invite(
    collaborator_id: str,
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("editor_write"))],
) -> CollaboratorResponse:
    row = collaborators.decline(session, user_id=user.id, collaborator_id=collaborator_id)
    session.commit()
    return _collaborator_response(session, row)


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
        season_number=payload.season_number,
        episode_kind=payload.episode_kind,
        synopsis=payload.synopsis,
    )
    session.commit()
    return episode_response(episode)


@router.get("/drama-series/{series_id}/episodes", response_model=list[DramaEpisodeResponse])
def list_episodes(
    series_id: str, user: CurrentUser, session: DbSession
) -> list[DramaEpisodeResponse]:
    rows = editor_service.list_episodes(session, user_id=user.id, series_id=series_id)
    turned = editor_service.episodes_with_script_turns(
        session, episode_ids=[item.id for item in rows]
    )
    return [episode_response(item, has_script_turns=item.id in turned) for item in rows]


@router.get("/drama-episodes/{episode_id}", response_model=DramaEpisodeResponse)
def get_episode(episode_id: str, user: CurrentUser, session: DbSession) -> DramaEpisodeResponse:
    episode = editor_service.get_episode(session, user_id=user.id, episode_id=episode_id)
    turned = editor_service.episodes_with_script_turns(session, episode_ids=[episode.id])
    return episode_response(episode, has_script_turns=episode.id in turned)


@router.patch("/drama-episodes/{episode_id}", response_model=DramaEpisodeResponse)
def update_episode(
    episode_id: str,
    payload: DramaEpisodeUpdateRequest,
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("editor_write"))],
) -> DramaEpisodeResponse:
    episode = editor_service.update_episode(
        session,
        user_id=user.id,
        episode_id=episode_id,
        title=payload.title,
        synopsis=payload.synopsis,
        episode_kind=payload.episode_kind,
        season_number=payload.season_number,
        episode_number=payload.episode_number,
        status=payload.status,
    )
    session.commit()
    turned = editor_service.episodes_with_script_turns(session, episode_ids=[episode.id])
    return episode_response(episode, has_script_turns=episode.id in turned)


@router.delete("/drama-episodes/{episode_id}", status_code=204)
def delete_episode(
    episode_id: str,
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("editor_write"))],
) -> None:
    editor_service.delete_episode(session, user_id=user.id, episode_id=episode_id)
    session.commit()


@router.post(
    "/drama-episodes/{episode_id}/content-links",
    response_model=EpisodeContentLinkResponse,
    status_code=201,
)
def create_content_link(
    episode_id: str,
    payload: EpisodeContentLinkCreateRequest,
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("editor_write"))],
) -> EpisodeContentLinkResponse:
    link = editor_service.create_content_link(
        session,
        user_id=user.id,
        episode_id=episode_id,
        content_type=payload.content_type,
        content_ref_id=payload.content_ref_id,
        role=payload.role,
    )
    session.commit()
    return content_link_response(link)


@router.get(
    "/drama-episodes/{episode_id}/content-links", response_model=list[EpisodeContentLinkResponse]
)
def list_content_links(
    episode_id: str, user: CurrentUser, session: DbSession
) -> list[EpisodeContentLinkResponse]:
    links = editor_service.list_content_links(
        session, user_id=user.id, episode_id=episode_id
    )
    # Heal upserts missing draft links; persist so the next read stays filled.
    session.commit()
    return [content_link_response(item) for item in links]


@router.delete("/drama-episodes/{episode_id}/content-links/{link_id}", status_code=204)
def delete_content_link(
    episode_id: str,
    link_id: str,
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("editor_write"))],
) -> None:
    editor_service.delete_content_link(
        session, user_id=user.id, episode_id=episode_id, link_id=link_id
    )
    session.commit()


@router.post("/drama-episodes/{episode_id}/set-canonical-work", response_model=DramaEpisodeResponse)
def set_canonical_work(
    episode_id: str,
    payload: EpisodeSetCanonicalWorkRequest,
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("editor_write"))],
) -> DramaEpisodeResponse:
    episode = editor_service.set_canonical_work(
        session, user_id=user.id, episode_id=episode_id, work_id=payload.work_id
    )
    session.commit()
    turned = editor_service.episodes_with_script_turns(session, episode_ids=[episode.id])
    return episode_response(episode, has_script_turns=episode.id in turned)


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
    analysis_id = _queue_analysis_if_needed(session, cut.source_asset_id)
    session.commit()
    if analysis_id:
        _enqueue_media_analysis(analysis_id)
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
    analysis_id = _queue_analysis_if_needed(session, cut.source_asset_id)
    session.commit()
    if analysis_id:
        _enqueue_media_analysis(analysis_id)
    return _cut_response(session, cut)


@router.get("/drama-episodes/{episode_id}/cuts", response_model=list[EpisodeCutResponse])
def list_cuts(episode_id: str, user: CurrentUser, session: DbSession) -> list[EpisodeCutResponse]:
    return [
        _cut_response(session, item)
        for item in editor_service.list_cuts(session, user_id=user.id, episode_id=episode_id)
    ]


@router.get("/drama-episodes/{episode_id}/exports", response_model=list[EpisodeExportResponse])
def list_episode_exports(
    episode_id: str, user: CurrentUser, session: DbSession
) -> list[EpisodeExportResponse]:
    """The episode's "最终成片" list — every export made from any of its
    cuts, each annotated with its publish state so the frontend can decide
    whether to offer "设为最终成片" (published), "去发布" (bound but not
    published) or download-only (never bound to a draft)."""
    episode = editor_service.get_episode(session, user_id=user.id, episode_id=episode_id)
    rows = export_service.list_exports_for_episode(session, user_id=user.id, episode_id=episode_id)
    return [
        EpisodeExportResponse(
            id=export.id,
            status=export.status,
            profile_key=variant.profile_key,
            width=variant.width,
            height=variant.height,
            format=variant.format,
            output_asset_id=export.output_asset_id,
            output_url=asset_url(session, export.output_asset_id),
            created_at=export.created_at,
            bound_draft_id=draft.id if draft else None,
            published_work_id=draft.published_work_id if draft else None,
            is_canonical=bool(
                draft
                and draft.published_work_id
                and draft.published_work_id == episode.canonical_work_id
            ),
        )
        for export, variant, draft in rows
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


@router.get(
    "/episode-cuts/{cut_id}/revisions",
    response_model=list[CutRevisionSummaryResponse],
)
def list_revisions(cut_id: str, user: CurrentUser, session: DbSession) -> list[CutRevisionSummaryResponse]:
    cut = editor_service._owned_cut(session, user_id=user.id, cut_id=cut_id)
    revisions = editor_service.list_revisions(session, user_id=user.id, cut_id=cut_id)
    return [
        _revision_summary_response(item, head_revision_id=cut.head_revision_id)
        for item in revisions
    ]


@router.post(
    "/episode-cuts/{cut_id}/revisions:restore",
    response_model=CutRevisionResponse,
    status_code=201,
)
def restore_revision(
    cut_id: str,
    payload: RevisionRestoreRequest,
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("editor_write"))],
) -> CutRevisionResponse:
    revision = editor_service.restore_revision(
        session,
        user_id=user.id,
        cut_id=cut_id,
        revision_id=payload.revision_id,
        expected_revision_id=payload.expected_revision_id,
        lease_id=payload.lease_id,
        lease_token=payload.lease_token,
    )
    session.commit()
    return _revision_response(session, revision)


@router.post("/episode-cuts/{cut_id}/edit-plans", status_code=202)
def create_edit_plan(
    cut_id: str,
    payload: EditPlanCreateRequest,
    user: CurrentUser,
    session: DbSession,
    _: Annotated[None, Depends(rate_limited("editor_write"))],
) -> StreamingResponse:
    from app.agents import editor_planner
    from app.api.agent_sse import SSE_HEADERS, iter_agent_sse
    from app.db import session_scope

    editor_flags.require_flag(session, editor_flags.FLAG_AI, user_id=user.id)
    cut = editor_service._owned_cut(session, user_id=user.id, cut_id=cut_id)
    head = editor_service.head_revision(session, cut)
    if head is None:
        raise ValidationFailed("剪辑还没有可编辑的修订。")
    chunks, finalize = editor_planner.stream_plan_timeline(
        session,
        user_id=user.id,
        cut=cut,
        revision=head,
        goal=payload.goal,
        max_commands=payload.max_commands,
    )

    def generate() -> Iterator[str]:
        def _finish() -> EditPlanResponse:
            with session_scope() as persist:
                outcome = finalize(persist)
                plan = editor_service.create_edit_plan(
                    persist,
                    user_id=user.id,
                    cut_id=cut_id,
                    goal=payload.goal,
                    commands=list(outcome.data.get("commands") or []),
                    summary=str(outcome.data.get("summary") or payload.goal),
                    agent_run_id=outcome.agent_run_id,
                    model=outcome.model,
                    warnings=[str(item) for item in (outcome.data.get("warnings") or [])],
                )
                persist.commit()
                return _plan_response(plan)

        yield from iter_agent_sse(
            chunks,
            _finish,
            lambda plan: plan.model_dump(mode="json"),
        )

    return StreamingResponse(
        generate(),
        status_code=202,
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


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


@router.post(
    "/media-assets/{asset_id}/transcriptions",
    response_model=EditorOperationResponse,
    status_code=202,
)
def request_transcription(
    asset_id: str, user: CurrentUser, session: DbSession
) -> EditorOperationResponse:
    """Enqueues speech-to-text for an owned video/audio asset.

    Mirrors the MCP tool `editor.request_transcription` — the poll-friendly
    `id` returned here is the same `MediaAnalysis` row fetched by
    `get_operation` below.
    """
    editor_flags.require_flag(session, editor_flags.FLAG_EDITOR, user_id=user.id)
    asset = session.get(Asset, asset_id)
    # 404 rather than 403 for someone else's asset, so this cannot be used to
    # probe for existence (same rationale as `GET /assets/{asset_id}`).
    if asset is None or asset.owner_user_id != user.id:
        raise NotFound("素材不存在。")
    analysis = media_analysis.enqueue_transcription(session, asset_id=asset_id)
    session.commit()
    celery_app.send_task("app.workers.tasks.run_editor_transcription", args=[analysis.id])
    return EditorOperationResponse(
        id=analysis.id,
        kind="media_analysis",
        status=analysis.status,
        progress=100 if analysis.status in {"succeeded", "degraded", "failed"} else 10,
    )


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
        analysis = session.get(MediaAnalysis, operation_id)
        if analysis is None:
            raise NotFound("操作不存在。")
        result: dict[str, Any] = {}
        if analysis.status in {"succeeded", "degraded"}:
            asset = session.get(Asset, analysis.asset_id)
            if asset is not None and asset.owner_user_id == user.id:
                result = {"transcript": analysis.transcript_json}
        return EditorOperationResponse(
            id=analysis.id,
            kind="media_analysis",
            status=analysis.status,
            progress=100 if analysis.status in {"succeeded", "degraded", "failed"} else 10,
            result=result,
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
