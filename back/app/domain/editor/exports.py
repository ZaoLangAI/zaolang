"""Browser export claim, heartbeat, bound upload and completion."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.editor import flags as editor_flags
from app.domain.editor import service as editor_service
from app.domain.editor import state_machine
from app.domain.editor.time import ticks_from_ms
from app.domain.errors import (
    BrowserRequired,
    Conflict,
    Forbidden,
    NotFound,
    OperationTerminal,
    ValidationFailed,
)
from app.domain.media import service as media_service
from app.domain.notifications import push as notifications
from app.domain.publishing import service as publishing
from app.models import (
    Asset,
    CutRevision,
    DeliveryVariant,
    Draft,
    DramaEpisode,
    EditorExport,
    EditorOperationEvent,
    EpisodeContentLink,
    EpisodeCut,
    GenerationJob,
    Notification,
    UploadSession,
    WorkVersion,
)
from app.models.base import utcnow
from app.models.enums import (
    TERMINAL_EDITOR_EXPORT_STATUSES,
    AssetRole,
    DeliveryVariantStatus,
    EditorExportStatus,
    EpisodeContentType,
    ModerationStatus,
)
from app.storage import s3

logger = logging.getLogger(__name__)

_IN_FLIGHT_EXPORT_STATUSES: frozenset[EditorExportStatus] = frozenset(
    status for status in EditorExportStatus if status not in TERMINAL_EDITOR_EXPORT_STATUSES
)
_STALE_LEASE_MESSAGE = "导出租约已过期，已自动结束。"
_PUBLISHED_EXPORT_MESSAGE = "该成片已发布，不能删除。"
_IN_FLIGHT_EXPORT_MESSAGE = "导出进行中，请先取消后再删除。"


def queue_exports(
    session: Session, *, user_id: str, variant_ids: list[str], operation_key: str | None = None
) -> list[EditorExport]:
    editor_flags.require_flag(session, editor_flags.FLAG_EXPORT, user_id=user_id)
    key = operation_key or secrets.token_urlsafe(12)
    reclaim_stale_exports(session)
    exports: list[EditorExport] = []
    for variant_id in variant_ids:
        variant = session.get(DeliveryVariant, variant_id)
        if variant is None:
            raise NotFound("交付变体不存在。")
        revision = session.get(CutRevision, variant.cut_revision_id)
        if revision is None:
            raise NotFound("修订不存在。")
        editor_service._owned_cut(session, user_id=user_id, cut_id=revision.cut_id)
        existing = session.scalar(
            select(EditorExport).where(
                EditorExport.variant_id == variant.id, EditorExport.operation_key == key
            )
        )
        if existing is not None:
            notifications.sync_export_notification(session, existing, user_id=user_id)
            exports.append(existing)
            continue
        _reclaim_or_conflict_inflight(session, variant.id)
        export = EditorExport(
            variant_id=variant.id,
            status=EditorExportStatus.QUEUED,
            operation_key=key,
            attempt=1,
        )
        session.add(export)
        session.flush()
        refreshed = session.get(DeliveryVariant, variant.id)
        assert refreshed is not None
        _ensure_variant_exporting(session, refreshed)
        editor_service.append_operation_event(
            session,
            export.id,
            event_type="queued",
            status=export.status,
            public_message="已加入导出队列，等待浏览器认领。",
        )
        notifications.sync_export_notification(session, export, user_id=user_id)
        exports.append(export)
    return exports


def claim_next(
    session: Session,
    *,
    user_id: str,
    runner_instance_id: str,
    capabilities: dict[str, object],
) -> EditorExport | None:
    editor_flags.require_flag(session, editor_flags.FLAG_EXPORT, user_id=user_id)
    if not capabilities.get("chrome_or_edge"):
        raise BrowserRequired()
    stmt = (
        select(EditorExport)
        .where(EditorExport.status == EditorExportStatus.QUEUED)
        .order_by(EditorExport.created_at.asc())
        .limit(20)
    )
    for export in session.scalars(stmt):
        variant = session.get(DeliveryVariant, export.variant_id)
        if variant is None:
            continue
        revision = session.get(CutRevision, variant.cut_revision_id)
        if revision is None:
            continue
        try:
            editor_service._owned_cut(session, user_id=user_id, cut_id=revision.cut_id)
        except (NotFound, Forbidden):
            continue
        claimed = state_machine.transition_export(
            session,
            export.id,
            EditorExportStatus.CLAIMED,
            claimed_by_user_id=user_id,
            runner_instance_id=runner_instance_id,
            lease_expires_at=utcnow() + dt.timedelta(seconds=45),
        )
        editor_service.append_operation_event(
            session,
            claimed.id,
            event_type="claimed",
            status=claimed.status,
            public_message="浏览器已认领导出。",
            progress=1,
        )
        return claimed
    return None


def heartbeat(
    session: Session,
    *,
    user_id: str,
    export_id: str,
    progress: int,
    stage: str,
) -> EditorExport:
    export = _owned_export(session, user_id=user_id, export_id=export_id)
    if EditorExportStatus(export.status) in TERMINAL_EDITOR_EXPORT_STATUSES:
        raise OperationTerminal()
    target = {
        "encoding": EditorExportStatus.ENCODING,
        "uploading": EditorExportStatus.UPLOADING,
        "verifying": EditorExportStatus.VERIFYING,
    }.get(stage)
    if target and export.status != target.value:
        try:
            export = state_machine.transition_export(session, export.id, target)
        except Exception:
            export = session.get(EditorExport, export.id) or export
    export.progress = max(0, min(100, progress))
    export.lease_expires_at = utcnow() + dt.timedelta(seconds=45)
    editor_service.append_operation_event(
        session,
        export.id,
        event_type="progress",
        status=export.status,
        public_message=f"导出进度 {export.progress}%",
        progress=export.progress,
    )
    session.flush()
    return export


def request_cancel(session: Session, *, user_id: str, export_id: str) -> EditorExport:
    export = _owned_export(session, user_id=user_id, export_id=export_id)
    export = state_machine.transition_export(
        session,
        export.id,
        EditorExportStatus.CANCEL_REQUESTED,
        cancel_requested_at=utcnow(),
    )
    editor_service.append_operation_event(
        session,
        export.id,
        event_type="cancel_requested",
        status=export.status,
        public_message="已请求取消导出。",
        progress=export.progress,
    )
    export = state_machine.transition_export(session, export.id, EditorExportStatus.CANCELLED)
    editor_service.append_operation_event(
        session,
        export.id,
        event_type="cancelled",
        status=export.status,
        public_message="导出已取消。",
        progress=export.progress,
    )
    _sync_variant_if_idle(
        session, export.variant_id, DeliveryVariantStatus.CANCELLED, exclude_id=export.id
    )
    return export


def retry_export(session: Session, *, user_id: str, export_id: str) -> EditorExport:
    original = _owned_export(session, user_id=user_id, export_id=export_id)
    if EditorExportStatus(original.status) not in {
        EditorExportStatus.FAILED,
        EditorExportStatus.CANCELLED,
    }:
        raise ValidationFailed("只有失败或已取消的导出可以重试。")
    retry = EditorExport(
        variant_id=original.variant_id,
        status=EditorExportStatus.QUEUED,
        operation_key=f"{original.operation_key}:r{original.attempt + 1}",
        attempt=original.attempt + 1,
    )
    session.add(retry)
    session.flush()
    variant = session.get(DeliveryVariant, original.variant_id)
    if variant is not None:
        _ensure_variant_exporting(session, variant)
    editor_service.append_operation_event(
        session,
        retry.id,
        event_type="queued",
        status=retry.status,
        public_message="已创建新的导出尝试。",
    )
    return retry


def presign_export_upload(
    session: Session,
    *,
    user_id: str,
    export_id: str,
    filename: str,
    mime_type: str,
    size_bytes: int,
    checksum_sha256: str,
) -> media_service.PresignedUpload:
    export = _owned_export(session, user_id=user_id, export_id=export_id)
    if EditorExportStatus(export.status) in TERMINAL_EDITOR_EXPORT_STATUSES:
        raise OperationTerminal()
    presigned = media_service.presign_upload(
        session,
        user_id=user_id,
        filename=filename,
        mime_type=mime_type,
        size_bytes=size_bytes,
        checksum_sha256=checksum_sha256,
        purpose="editor_export",
    )
    presigned.upload_session.bound_export_id = export.id
    session.flush()
    return presigned


def complete_export(
    session: Session,
    *,
    user_id: str,
    export_id: str,
    upload_session_id: str,
) -> EditorExport:
    export = _owned_export(session, user_id=user_id, export_id=export_id)
    if export.status == EditorExportStatus.SUCCEEDED.value and export.output_asset_id:
        return export
    asset = media_service.complete_upload(
        session, user_id=user_id, upload_session_id=upload_session_id
    )
    upload_row = session.get(UploadSession, upload_session_id)
    if upload_row is None or upload_row.bound_export_id != export.id:
        raise ValidationFailed("上传会话未绑定到该导出。")
    if asset.role != AssetRole.EDITOR_EXPORT:
        raise ValidationFailed("导出必须使用 editor_export 用途上传。")
    # The browser runner heartbeats `encoding` through 100%, then PUTs and
    # calls complete without necessarily having stepped through
    # uploading/verifying. Walk the legal edges so a finished upload is not
    # rejected as `encoding → succeeded`.
    export = _advance_export_to_verifying(session, export)
    export = state_machine.transition_export(
        session,
        export.id,
        EditorExportStatus.SUCCEEDED,
        output_asset_id=asset.id,
        checksum_sha256=asset.checksum_sha256,
        size_bytes=asset.size_bytes,
        progress=100,
        finished_at=utcnow(),
    )
    variant = session.get(DeliveryVariant, export.variant_id)
    if variant is not None:
        state_machine.transition_variant(session, variant.id, DeliveryVariantStatus.SUCCEEDED)
    # An exported cut is AI output too: it gets the same (unsigned) provenance
    # claim a generated asset does, next to the AIGC tag the browser runner
    # writes into the file's own metadata. One manifest per asset.
    if media_service.provenance_for(session, asset.id) is None:
        media_service.record_provenance(
            session,
            asset=asset,
            generation_job_id=None,
            details={
                "zaolang.editor_export": {
                    "export_id": export.id,
                    "variant_id": export.variant_id,
                }
            },
        )
    editor_service.append_operation_event(
        session,
        export.id,
        event_type="succeeded",
        status=export.status,
        public_message="导出已登记为素材。",
        progress=100,
        payload={"asset_id": asset.id},
    )
    return export


def fail_export(
    session: Session, *, user_id: str, export_id: str, code: str, message: str
) -> EditorExport:
    export = _owned_export(session, user_id=user_id, export_id=export_id)
    return _fail_export_row(session, export, code=code, message=message)


def reclaim_stale_exports(session: Session) -> int:
    """Fails in-flight exports whose runner lease has expired.

    Queued rows have no lease and stay queued until a browser claims them or
    a later `queue_exports` replaces them. Claimed/encoding/uploading rows
    that missed their 45s heartbeat are dead — the blob only lived in that
    browser — so they become `failed` and the variant drops to `failed`
    when nothing else is still running.
    """
    now = utcnow()
    rows = list(
        session.scalars(
            select(EditorExport).where(
                EditorExport.status.in_([status.value for status in _IN_FLIGHT_EXPORT_STATUSES]),
                EditorExport.lease_expires_at.is_not(None),
                EditorExport.lease_expires_at <= now,
            )
        )
    )
    reclaimed = 0
    for export in rows:
        before = export.status
        _fail_export_row(session, export, code="stale_lease", message=_STALE_LEASE_MESSAGE)
        if before != EditorExportStatus.FAILED.value:
            reclaimed += 1
    return reclaimed


def bind_draft_export(
    session: Session,
    *,
    user_id: str,
    draft_id: str,
    export_id: str,
    confirmed: bool,
) -> Draft:
    if not confirmed:
        raise ValidationFailed("必须确认绑定该导出结果。")
    editor_flags.require_flag(session, editor_flags.FLAG_EXPORT, user_id=user_id)
    draft = session.get(Draft, draft_id)
    if draft is None or draft.user_id != user_id:
        raise NotFound("草稿不存在。")
    if draft.published_work_id is not None:
        raise Conflict("草稿已经发布。")
    export = _owned_export(session, user_id=user_id, export_id=export_id)
    if export.status != EditorExportStatus.SUCCEEDED.value or not export.output_asset_id:
        raise ValidationFailed("只能绑定已成功的导出。")
    asset = session.get(Asset, export.output_asset_id)
    if asset is None or asset.owner_user_id != user_id:
        raise Forbidden("导出素材不属于当前用户。")
    if asset.moderation_status == ModerationStatus.REJECTED:
        raise ValidationFailed("导出素材未通过审核。")
    variant = session.get(DeliveryVariant, export.variant_id)
    revision = session.get(CutRevision, variant.cut_revision_id) if variant else None
    draft.output_asset_id = asset.id
    draft.source_cut_revision_id = revision.id if revision else None
    draft.delivery_variant_id = variant.id if variant else None
    draft.editor_export_id = export.id
    session.flush()
    return draft


def ensure_export_bound_draft(
    session: Session,
    *,
    user_id: str,
    export_id: str,
    confirmed: bool,
    draft_id: str | None = None,
) -> Draft:
    """Bind a succeeded export to a draft, minting one when none is given.

    Reuses the unpublished source-generation draft (job or content-link whose
    output is this cut's source asset) so the job-page bind path stays one
    draft. A published source draft is skipped and a new one is created —
    `bind_draft_export` refuses an already-published row.
    """
    if not confirmed:
        raise ValidationFailed("必须确认绑定该导出结果。")
    editor_flags.require_flag(session, editor_flags.FLAG_EXPORT, user_id=user_id)
    export = _owned_export(session, user_id=user_id, export_id=export_id)
    if export.status != EditorExportStatus.SUCCEEDED.value or not export.output_asset_id:
        raise ValidationFailed("只能绑定已成功的导出。")
    existing = session.scalar(select(Draft).where(Draft.editor_export_id == export.id))
    if existing is not None:
        if existing.published_work_id is not None:
            raise Conflict("草稿已经发布。")
        return existing
    target_id = draft_id or _source_unpublished_draft_id(session, user_id=user_id, export=export)
    if target_id is None:
        episode = _episode_for_export(session, export)
        minted = publishing.create_draft(
            session,
            user_id=user_id,
            source_work_id=None,
            title=episode.title if episode else None,
            params={"link_episode_id": episode.id} if episode else {},
        )
        target_id = minted.id
    return bind_draft_export(
        session,
        user_id=user_id,
        draft_id=target_id,
        export_id=export.id,
        confirmed=True,
    )


def _source_unpublished_draft_id(
    session: Session, *, user_id: str, export: EditorExport
) -> str | None:
    cut = _cut_for_export(session, export)
    if cut is None:
        return None
    if cut.source_job_id:
        job = session.get(GenerationJob, cut.source_job_id)
        if job is not None and job.user_id == user_id and job.draft_id:
            draft = session.get(Draft, job.draft_id)
            if draft is not None and draft.user_id == user_id and draft.published_work_id is None:
                return draft.id
    if not cut.source_asset_id:
        return None
    links = session.scalars(
        select(EpisodeContentLink).where(
            EpisodeContentLink.episode_id == cut.episode_id,
            EpisodeContentLink.content_type == EpisodeContentType.DRAFT,
        )
    )
    for link in links:
        draft = session.get(Draft, link.content_ref_id)
        if (
            draft is not None
            and draft.user_id == user_id
            and draft.published_work_id is None
            and draft.output_asset_id == cut.source_asset_id
        ):
            return draft.id
    return None


def _cut_for_export(session: Session, export: EditorExport) -> EpisodeCut | None:
    variant = session.get(DeliveryVariant, export.variant_id)
    if variant is None:
        return None
    revision = session.get(CutRevision, variant.cut_revision_id)
    if revision is None:
        return None
    return session.get(EpisodeCut, revision.cut_id)


def _episode_for_export(session: Session, export: EditorExport) -> DramaEpisode | None:
    cut = _cut_for_export(session, export)
    if cut is None:
        return None
    return session.get(DramaEpisode, cut.episode_id)


def list_exports_for_episode(
    session: Session, *, user_id: str, episode_id: str
) -> list[tuple[EditorExport, DeliveryVariant, Draft | None]]:
    """Every editor export made from any cut belonging to this episode,
    newest first, each paired with its delivery variant and — if one
    exists — the draft it was bound into via `bind_draft_export`. An
    export carries no forward pointer to whichever draft later claimed it,
    so the draft is found by the reverse lookup `Draft.editor_export_id ==
    export.id` instead. This is the "最终成片" list on the episode page —
    it replaces the old cuts list, which moved into the editor itself."""
    editor_flags.require_flag(session, editor_flags.FLAG_EDITOR, user_id=user_id)
    editor_service._owned_episode(session, user_id=user_id, episode_id=episode_id)
    cut_ids = list(
        session.scalars(select(EpisodeCut.id).where(EpisodeCut.episode_id == episode_id))
    )
    if not cut_ids:
        return []
    revision_ids = list(
        session.scalars(select(CutRevision.id).where(CutRevision.cut_id.in_(cut_ids)))
    )
    if not revision_ids:
        return []
    variants = list(
        session.scalars(
            select(DeliveryVariant).where(DeliveryVariant.cut_revision_id.in_(revision_ids))
        )
    )
    variant_by_id = {variant.id: variant for variant in variants}
    if not variant_by_id:
        return []
    exports = list(
        session.scalars(
            select(EditorExport)
            .where(EditorExport.variant_id.in_(variant_by_id.keys()))
            .order_by(EditorExport.created_at.desc())
        )
    )
    if not exports:
        return []
    drafts = list(
        session.scalars(
            select(Draft).where(Draft.editor_export_id.in_([item.id for item in exports]))
        )
    )
    draft_by_export_id = {draft.editor_export_id: draft for draft in drafts}
    return [
        (export, variant_by_id[export.variant_id], draft_by_export_id.get(export.id))
        for export in exports
    ]


def delete_export(session: Session, *, user_id: str, export_id: str) -> None:
    """Remove one unpublished export from the episode's 最终成片 list.

    Ownership is `_owned_export` (owner-only — collaborators cannot
    touch timeline/export). A published bind, or a `WorkVersion` that
    already stamped this export, is 422 — same gate as tearing down
    the whole episode. In-flight rows must be cancelled first. The
    bound draft is unbound, not deleted; the output asset and
    delivery variant stay (other exports may share the variant).
    """
    editor_flags.require_flag(session, editor_flags.FLAG_EXPORT, user_id=user_id)
    export = _owned_export(session, user_id=user_id, export_id=export_id)
    if EditorExportStatus(export.status) not in TERMINAL_EDITOR_EXPORT_STATUSES:
        raise ValidationFailed(_IN_FLIGHT_EXPORT_MESSAGE)
    drafts = list(session.scalars(select(Draft).where(Draft.editor_export_id == export.id)))
    if any(draft.published_work_id for draft in drafts):
        raise ValidationFailed(_PUBLISHED_EXPORT_MESSAGE)
    published_version = session.scalar(
        select(WorkVersion.id).where(WorkVersion.editor_export_id == export.id).limit(1)
    )
    if published_version is not None:
        raise ValidationFailed(_PUBLISHED_EXPORT_MESSAGE)

    for draft in drafts:
        draft.editor_export_id = None
        draft.delivery_variant_id = None
        draft.source_cut_revision_id = None
    session.flush()

    for link in session.scalars(
        select(EpisodeContentLink).where(
            EpisodeContentLink.content_type == EpisodeContentType.EDITOR_EXPORT,
            EpisodeContentLink.content_ref_id == export.id,
        )
    ):
        session.delete(link)
    for upload in session.scalars(
        select(UploadSession).where(UploadSession.bound_export_id == export.id)
    ):
        upload.bound_export_id = None
    for notification in session.scalars(
        select(Notification).where(
            Notification.target_type == "editor_export",
            Notification.target_id == export.id,
        )
    ):
        session.delete(notification)
    for event in session.scalars(
        select(EditorOperationEvent).where(EditorOperationEvent.operation_id == export.id)
    ):
        session.delete(event)
    session.flush()
    session.delete(export)
    session.flush()


def _lease_is_live(export: EditorExport, *, now: dt.datetime | None = None) -> bool:
    if export.lease_expires_at is None:
        return False
    return export.lease_expires_at > (now or utcnow())


def _inflight_exports(
    session: Session, variant_id: str, *, exclude_id: str | None = None
) -> list[EditorExport]:
    rows = list(
        session.scalars(
            select(EditorExport).where(
                EditorExport.variant_id == variant_id,
                EditorExport.status.in_([status.value for status in _IN_FLIGHT_EXPORT_STATUSES]),
            )
        )
    )
    if exclude_id is None:
        return rows
    return [row for row in rows if row.id != exclude_id]


def _advance_export_to_verifying(session: Session, export: EditorExport) -> EditorExport:
    steps = {
        EditorExportStatus.CLAIMED: EditorExportStatus.ENCODING,
        EditorExportStatus.ENCODING: EditorExportStatus.UPLOADING,
        EditorExportStatus.UPLOADING: EditorExportStatus.VERIFYING,
    }
    status = EditorExportStatus(export.status)
    while status in steps:
        export = state_machine.transition_export(session, export.id, steps[status])
        status = EditorExportStatus(export.status)
    return export


def _ensure_variant_exporting(session: Session, variant: DeliveryVariant) -> DeliveryVariant:
    if variant.status == DeliveryVariantStatus.EXPORTING.value:
        return variant
    return state_machine.transition_variant(session, variant.id, DeliveryVariantStatus.EXPORTING)


def _sync_variant_if_idle(
    session: Session,
    variant_id: str,
    target: DeliveryVariantStatus,
    *,
    exclude_id: str | None = None,
) -> None:
    if _inflight_exports(session, variant_id, exclude_id=exclude_id):
        return
    variant = session.get(DeliveryVariant, variant_id)
    if variant is None or variant.status != DeliveryVariantStatus.EXPORTING.value:
        return
    state_machine.transition_variant(session, variant_id, target)


def _fail_export_row(
    session: Session, export: EditorExport, *, code: str, message: str
) -> EditorExport:
    if EditorExportStatus(export.status) in TERMINAL_EDITOR_EXPORT_STATUSES:
        return export
    try:
        export = state_machine.transition_export(
            session,
            export.id,
            EditorExportStatus.FAILED,
            failure_code=code,
            failure_message=message,
            finished_at=utcnow(),
        )
    except OperationTerminal:
        refreshed = session.get(EditorExport, export.id)
        return refreshed or export
    editor_service.append_operation_event(
        session,
        export.id,
        event_type="failed",
        status=export.status,
        public_message=message,
        payload={"code": code},
    )
    logger.warning(
        "editor_export_failed",
        extra={"export_id": export.id, "code": code, "failure_message": message},
    )
    _sync_variant_if_idle(
        session, export.variant_id, DeliveryVariantStatus.FAILED, exclude_id=export.id
    )
    return export


def _reclaim_or_conflict_inflight(session: Session, variant_id: str) -> None:
    inflight = _inflight_exports(session, variant_id)
    if any(_lease_is_live(row) for row in inflight):
        raise Conflict("该规格正在导出，请等待当前任务完成。")
    for row in inflight:
        _fail_export_row(session, row, code="stale_lease", message=_STALE_LEASE_MESSAGE)


def _owned_export(session: Session, *, user_id: str, export_id: str) -> EditorExport:
    export = session.get(EditorExport, export_id)
    if export is None:
        raise NotFound("导出任务不存在。")
    variant = session.get(DeliveryVariant, export.variant_id)
    if variant is None:
        raise NotFound("交付变体不存在。")
    revision = session.get(CutRevision, variant.cut_revision_id)
    if revision is None:
        raise NotFound("修订不存在。")
    editor_service._owned_cut(session, user_id=user_id, cut_id=revision.cut_id)
    return export


def spec_hash(spec: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(spec, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def object_exists(object_key: str) -> bool:
    return s3.head_object(object_key) is not None


def ticks_of(asset: Asset) -> int:
    return ticks_from_ms(asset.duration_ms)


def stamp_work_version_export(version: WorkVersion, export: EditorExport) -> None:
    version.editor_export_id = export.id
