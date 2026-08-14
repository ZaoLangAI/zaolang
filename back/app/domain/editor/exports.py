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
from app.domain.editor.time import EXPORT_MAX_DURATION_TICKS, EXPORT_MAX_PIXELS, ticks_from_ms
from app.domain.errors import (
    BrowserRequired,
    Conflict,
    Forbidden,
    NotFound,
    OperationTerminal,
    ValidationFailed,
)
from app.domain.media import service as media_service
from app.models import (
    Asset,
    CutRevision,
    DeliveryVariant,
    Draft,
    EditorExport,
    UploadSession,
    WorkVersion,
)
from app.models.base import utcnow
from app.models.enums import (
    TERMINAL_EDITOR_EXPORT_STATUSES,
    AssetRole,
    DeliveryVariantStatus,
    EditorExportStatus,
    ModerationStatus,
)
from app.storage import s3

logger = logging.getLogger(__name__)


def queue_exports(
    session: Session, *, user_id: str, variant_ids: list[str], operation_key: str | None = None
) -> list[EditorExport]:
    editor_flags.require_flag(session, editor_flags.FLAG_EXPORT, user_id=user_id)
    key = operation_key or secrets.token_urlsafe(12)
    exports: list[EditorExport] = []
    for variant_id in variant_ids:
        variant = session.get(DeliveryVariant, variant_id)
        if variant is None:
            raise NotFound("交付变体不存在。")
        revision = session.get(CutRevision, variant.cut_revision_id)
        if revision is None:
            raise NotFound("修订不存在。")
        editor_service._owned_cut(session, user_id=user_id, cut_id=revision.cut_id)
        pixels = variant.width * variant.height
        if pixels > EXPORT_MAX_PIXELS or revision.duration_ticks > EXPORT_MAX_DURATION_TICKS:
            raise ValidationFailed("超出浏览器内存导出上限。")
        existing = session.scalar(
            select(EditorExport).where(
                EditorExport.variant_id == variant.id, EditorExport.operation_key == key
            )
        )
        if existing is not None:
            exports.append(existing)
            continue
        export = EditorExport(
            variant_id=variant.id,
            status=EditorExportStatus.QUEUED,
            operation_key=key,
            attempt=1,
        )
        session.add(export)
        session.flush()
        state_machine.transition_variant(session, variant.id, DeliveryVariantStatus.EXPORTING)
        editor_service.append_operation_event(
            session,
            export.id,
            event_type="queued",
            status=export.status,
            public_message="已加入导出队列，等待浏览器认领。",
        )
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
    export = state_machine.transition_export(
        session,
        export.id,
        EditorExportStatus.FAILED,
        failure_code=code,
        failure_message=message,
        finished_at=utcnow(),
    )
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
        extra={"export_id": export.id, "code": code, "message": message},
    )
    return export


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
