"""站内通知落库 + APNs 推送派发的统一入口。

本地/测试环境没有真实 APNs Key（`.p8` + Team ID + Key ID），`send_push` 只打日志占位，
接口契约与调用点已经就位——接真实 APNs 只需要替换这一个函数的函数体，换成
`aioapns`/`httpx` 直连 `api.push.apple.com` 的 HTTP/2 请求，调用点不用动。

创作类通知（生成任务 / 短剧导出 / 草稿发布审核）按 `(user_id, target_type, target_id)` upsert
同一行，随记录状态更新；社交与审核仍走 `notify()` 插入。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    CreationSkill,
    CutRevision,
    DeliveryVariant,
    Device,
    Draft,
    DramaEpisode,
    EditorExport,
    EpisodeCut,
    GenerationJob,
    Notification,
    Series,
    StyleGalleryEntry,
)
from app.models.base import utcnow
from app.models.enums import (
    CreationSkillCategory,
    EditorExportStatus,
    JobOrigin,
    JobStatus,
    NotificationType,
)
from app.realtime import publisher

logger = logging.getLogger(__name__)

PROMPT_EXCERPT_MAX = 40
SCRIPT_ERROR_EXCERPT_MAX = 200
DRAMA_EXPORT_OPERATION = "drama_export"
CREATION_TARGET_JOB = "generation_job"
CREATION_TARGET_EXPORT = "editor_export"
CREATION_TARGET_SCRIPT = "episode_script"
CREATION_TARGET_DRAFT = "draft"

_JOB_ACTIONABLE = frozenset(
    {
        JobStatus.AWAITING_INPUT,
        JobStatus.SUCCEEDED,
        JobStatus.FAILED,
        JobStatus.CANCELLED,
        JobStatus.EXPIRED,
    }
)
_EXPORT_ACTIONABLE = frozenset(
    {
        EditorExportStatus.SUCCEEDED,
        EditorExportStatus.FAILED,
        EditorExportStatus.CANCELLED,
    }
)
_EXPORT_RUNNING = frozenset(
    {
        EditorExportStatus.CLAIMED,
        EditorExportStatus.ENCODING,
        EditorExportStatus.UPLOADING,
        EditorExportStatus.VERIFYING,
    }
)
# Script generation has no persisted status enum of its own (see
# `script_writing_service` — generation is still a single synchronous SSE
# request, not a tracked job row); these are the plain strings
# `sync_script_notification`'s callers pass in.
_SCRIPT_ACTIONABLE = frozenset({"succeeded", "failed"})


def notify(
    session: Session,
    *,
    user_id: str,
    type: NotificationType,
    title_key: str,
    payload: dict[str, Any] | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
) -> Notification:
    """写一行站内通知，并尽力推一次 APNs。调用方负责在这之前/之后自己 commit——
    这里不 commit，避免和调用方已经开着的事务打架（例如任务状态机的 `_emit`）。
    """
    record = Notification(
        user_id=user_id,
        type=type,
        title_key=title_key,
        payload_json=payload or {},
        target_type=target_type,
        target_id=target_id,
    )
    session.add(record)
    session.flush()
    _dispatch_push(session, user_id=user_id, title_key=title_key, payload=payload or {})
    _publish(record)
    return record


def sync_job_notification(session: Session, job: GenerationJob) -> Notification | None:
    """Upsert the one notification row that tracks this C-end generation job."""
    if job.origin == JobOrigin.SANDBOX:
        return None
    status = JobStatus(job.status)
    ntype, title_key = job_type_and_key(status)
    bump = status in _JOB_ACTIONABLE
    return sync_creation_notification(
        session,
        user_id=job.user_id,
        type=ntype,
        title_key=title_key,
        payload=job_payload(session, job),
        target_type=CREATION_TARGET_JOB,
        target_id=job.id,
        bump_unread=bump,
        dispatch_push=bump,
    )


def sync_export_notification(
    session: Session, export: EditorExport, *, user_id: str | None = None
) -> Notification | None:
    """Upsert the one notification row that tracks this drama export."""
    context = resolve_export_context(session, export)
    owner_id = user_id or (context.user_id if context else None)
    if owner_id is None:
        return None
    status = EditorExportStatus(export.status)
    ntype, title_key = export_type_and_key(status)
    bump = status in _EXPORT_ACTIONABLE
    return sync_creation_notification(
        session,
        user_id=owner_id,
        type=ntype,
        title_key=title_key,
        payload=export_payload(export, context),
        target_type=CREATION_TARGET_EXPORT,
        target_id=export.id,
        bump_unread=bump,
        dispatch_push=bump,
    )


def sync_script_notification(
    session: Session,
    *,
    episode: DramaEpisode,
    series: Series,
    status: str,
    kind: str,
    turn_no: int | None = None,
    error: str | None = None,
) -> Notification:
    """Upsert the one notification row that tracks this script's most
    recent generation attempt (first draft, revision, or a first-draft
    retry — all three funnel through here with `kind="draft"`/`"revise"`).

    `status` is one of `"generating"`/`"succeeded"`/`"failed"` — plain
    strings, not a persisted enum, since a script generation is still a
    single synchronous SSE request with no tracked job row (see
    `script_writing_service`'s module docstring); this call is the only
    place that state briefly exists. `"generating"` never bumps unread or
    pushes, matching the "开始生成" scope decided for this feature — only
    `"succeeded"`/`"failed"` are actionable, same split as
    `_JOB_ACTIONABLE`/`_EXPORT_ACTIONABLE`.
    """
    ntype, title_key = script_type_and_key(status)
    bump = status in _SCRIPT_ACTIONABLE
    return sync_creation_notification(
        session,
        user_id=series.owner_user_id,
        type=ntype,
        title_key=title_key,
        payload=script_payload(
            episode=episode, series=series, kind=kind, turn_no=turn_no, error=error
        ),
        target_type=CREATION_TARGET_SCRIPT,
        target_id=episode.id,
        bump_unread=bump,
        dispatch_push=bump,
    )


def sync_draft_publish_notification(
    session: Session,
    *,
    draft: Draft,
    published: bool,
    work_id: str | None = None,
    public_message: str | None = None,
) -> Notification:
    """Upserts the one notification that tracks this draft's publish review."""
    if published:
        ntype = NotificationType.DRAFT_PUBLISHED
        title_key = "notification.draft_published"
    else:
        ntype = NotificationType.DRAFT_PUBLISH_REJECTED
        title_key = "notification.draft_publish_rejected"
    payload: dict[str, Any] = {"title": draft.title or "", "draft_id": draft.id}
    if work_id:
        payload["work_id"] = work_id
    if public_message:
        payload["public_message"] = public_message
    return sync_creation_notification(
        session,
        user_id=draft.user_id,
        type=ntype,
        title_key=title_key,
        payload=payload,
        target_type=CREATION_TARGET_DRAFT,
        target_id=draft.id,
        bump_unread=True,
        dispatch_push=True,
    )


def sync_creation_notification(
    session: Session,
    *,
    user_id: str,
    type: NotificationType,
    title_key: str,
    payload: dict[str, Any],
    target_type: str,
    target_id: str,
    bump_unread: bool,
    dispatch_push: bool,
) -> Notification:
    """Find-or-create the creation notification and apply the latest status."""
    record = _find_creation(session, user_id=user_id, target_type=target_type, target_id=target_id)
    if record is None:
        record = Notification(
            user_id=user_id,
            type=type,
            title_key=title_key,
            payload_json=dict(payload),
            target_type=target_type,
            target_id=target_id,
        )
        nested = session.begin_nested()
        try:
            session.add(record)
            session.flush()
            nested.commit()
        except IntegrityError:
            nested.rollback()
            existing = _find_creation(
                session, user_id=user_id, target_type=target_type, target_id=target_id
            )
            if existing is None:
                raise
            record = existing
            _apply_creation_update(
                record, type=type, title_key=title_key, payload=payload, bump_unread=bump_unread
            )
            session.flush()
        if dispatch_push:
            _dispatch_push(session, user_id=user_id, title_key=title_key, payload=payload)
        _publish(record)
        return record

    _apply_creation_update(
        record, type=type, title_key=title_key, payload=payload, bump_unread=bump_unread
    )
    session.flush()
    if dispatch_push:
        _dispatch_push(session, user_id=user_id, title_key=title_key, payload=payload)
    _publish(record)
    return record


def present_notification(
    session: Session,
    record: Notification,
    *,
    jobs: dict[str, GenerationJob] | None = None,
    exports: dict[str, EditorExport] | None = None,
) -> tuple[NotificationType, str, dict[str, Any]]:
    """Overlay live job/export fields so a missed sync still reads correctly."""
    payload = dict(record.payload_json or {})
    if record.target_type == CREATION_TARGET_JOB and record.target_id:
        job = (jobs or {}).get(record.target_id)
        if job is None:
            job = session.get(GenerationJob, record.target_id)
        if job is not None:
            payload.update(job_payload(session, job))
            return (*job_type_and_key(JobStatus(job.status)), payload)
    if record.target_type == CREATION_TARGET_EXPORT and record.target_id:
        export = (exports or {}).get(record.target_id)
        if export is None:
            export = session.get(EditorExport, record.target_id)
        if export is not None:
            context = resolve_export_context(session, export)
            payload.update(export_payload(export, context))
            return (*export_type_and_key(EditorExportStatus(export.status)), payload)
    try:
        ntype = NotificationType(record.type)
    except ValueError:
        ntype = NotificationType.SYSTEM
    return ntype, record.title_key, payload


def job_type_and_key(status: JobStatus) -> tuple[NotificationType, str]:
    if status is JobStatus.SUCCEEDED:
        return NotificationType.JOB_SUCCEEDED, "notification.job_succeeded"
    if status is JobStatus.FAILED:
        return NotificationType.JOB_FAILED, "notification.job_failed"
    if status is JobStatus.CANCELLED:
        return NotificationType.JOB_CANCELLED, "notification.job_cancelled"
    if status is JobStatus.EXPIRED:
        return NotificationType.JOB_CANCELLED, "notification.job_expired"
    if status is JobStatus.AWAITING_INPUT:
        return NotificationType.JOB_PROGRESS, "notification.job_awaiting_input"
    if status in (JobStatus.RUNNING, JobStatus.SUBMITTED):
        return NotificationType.JOB_PROGRESS, "notification.job_running"
    return NotificationType.JOB_PROGRESS, "notification.job_queued"


def export_type_and_key(status: EditorExportStatus) -> tuple[NotificationType, str]:
    if status is EditorExportStatus.SUCCEEDED:
        return NotificationType.JOB_SUCCEEDED, "notification.export_succeeded"
    if status is EditorExportStatus.FAILED:
        return NotificationType.JOB_FAILED, "notification.export_failed"
    if status in (EditorExportStatus.CANCELLED, EditorExportStatus.CANCEL_REQUESTED):
        return NotificationType.JOB_CANCELLED, "notification.export_cancelled"
    if status in _EXPORT_RUNNING:
        return NotificationType.JOB_PROGRESS, "notification.export_running"
    return NotificationType.JOB_PROGRESS, "notification.export_queued"


def script_type_and_key(status: str) -> tuple[NotificationType, str]:
    if status == "succeeded":
        return NotificationType.JOB_SUCCEEDED, "notification.script_succeeded"
    if status == "failed":
        return NotificationType.JOB_FAILED, "notification.script_failed"
    return NotificationType.JOB_PROGRESS, "notification.script_generating"


def script_payload(
    *,
    episode: DramaEpisode,
    series: Series,
    kind: str,
    turn_no: int | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "episode_id": episode.id,
        "series_id": series.id,
        "title": episode.title,
        "kind": kind,
    }
    if turn_no is not None:
        payload["turn_no"] = turn_no
    if error:
        payload["error"] = error[:SCRIPT_ERROR_EXCERPT_MAX]
    return payload


def partial_delivery(job: GenerationJob) -> dict[str, int]:
    """A multi-pass image job a later pass of which failed still succeeds
    with the images it delivered and settles per image (P2-0,
    `workflows.nodes._finish_partial_asset_job`). Its card workspace shows
    only the images, so the notification is where `delivered_outputs` /
    `requested_outputs` / `refunded_credits` reach the user. `{}` otherwise.
    """
    # Imported here: `jobs.service` imports this module.
    from app.domain.jobs import service as jobs_service

    if job.status != JobStatus.SUCCEEDED:
        return {}
    requested = jobs_service.requested_outputs_of(job)
    delivered = len(
        job.output_asset_ids_json or ([job.output_asset_id] if job.output_asset_id else [])
    )
    if requested <= 1 or not 0 < delivered < requested:
        return {}
    refunded = max(0, job.reserved_credits - (job.actual_credits or 0))
    return {
        "delivered_outputs": delivered,
        "requested_outputs": requested,
        "refunded_credits": refunded,
    }


def job_payload(session: Session, job: GenerationJob) -> dict[str, Any]:
    params = job.request_json if isinstance(job.request_json, dict) else {}
    prompt = str(params.get("prompt") or "")
    payload: dict[str, Any] = {
        "job_id": job.id,
        "status": job.status,
        "operation": job.operation,
        "quality_tier": job.quality_tier,
        "prompt_excerpt": prompt[:PROMPT_EXCERPT_MAX],
        "is_remix": bool(job.source_work_version_id),
    }
    if job.draft_id:
        # Lets the frontend route video-creation jobs back into the studio
        # (inline progress/version history) instead of `/jobs/[jobId]` — see
        # `notification-format.ts#targetHref`.
        payload["draft_id"] = job.draft_id
    # Image jobs open their card's workspace (`front/src/lib/asset-job-href.ts`):
    # the card the output filed into (`linked_*`, set at write-back — the
    # list overlay re-reads it), else the one the request named (`target_*`),
    # and the look / variant / condition it targeted. A general or cover
    # image names none and lands on its read-only job page.
    asset_kind = params.get("asset_kind")
    if isinstance(asset_kind, str) and asset_kind:
        payload["asset_kind"] = asset_kind
    for key, value in (
        ("linked_character_id", job.linked_character_id),
        ("linked_scene_id", job.linked_scene_id),
        ("linked_prop_id", job.linked_prop_id),
        ("target_character_id", params.get("target_character_id")),
        ("target_scene_id", params.get("target_scene_id")),
        ("target_prop_id", params.get("target_prop_id")),
        ("target_variant_id", params.get("target_variant_id")),
    ):
        if isinstance(value, str) and value:
            payload[key] = value
    payload.update(partial_delivery(job))
    profile = params.get("shortform_profile")
    if isinstance(profile, str) and profile:
        payload["shortform_profile"] = profile
    style_id = params.get("style_gallery_id")
    if isinstance(style_id, str) and style_id:
        entry = session.get(StyleGalleryEntry, style_id)
        if entry is not None:
            payload["style_name"] = entry.label_zh
    character_ids = params.get("character_ids") or []
    if isinstance(character_ids, list) and character_ids:
        # Characters are stored as `CreationSkill(category=character)` — see
        # `app.domain.characters.service`. Read the title straight off the
        # row rather than importing the characters domain here.
        character = session.get(CreationSkill, str(character_ids[0]))
        if character is not None and character.category == CreationSkillCategory.CHARACTER:
            payload["character_name"] = character.title
    return payload


def export_payload(export: EditorExport, context: ExportContext | None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "export_id": export.id,
        "status": export.status,
        "operation": DRAMA_EXPORT_OPERATION,
    }
    if context is not None:
        payload["series_title"] = context.series_title
        payload["episode_title"] = context.episode_title
        payload["cut_id"] = context.cut_id
    return payload


@dataclass(frozen=True, slots=True)
class ExportContext:
    user_id: str
    series_title: str
    episode_title: str
    cut_id: str


def resolve_export_context(session: Session, export: EditorExport) -> ExportContext | None:
    variant = session.get(DeliveryVariant, export.variant_id)
    if variant is None:
        return None
    revision = session.get(CutRevision, variant.cut_revision_id)
    if revision is None:
        return None
    cut = session.get(EpisodeCut, revision.cut_id)
    if cut is None:
        return None
    episode = session.get(DramaEpisode, cut.episode_id)
    if episode is None:
        return None
    series = session.get(Series, episode.series_id)
    if series is None:
        return None
    return ExportContext(
        user_id=series.owner_user_id,
        series_title=series.title,
        episode_title=episode.title,
        cut_id=cut.id,
    )


def _find_creation(
    session: Session, *, user_id: str, target_type: str, target_id: str
) -> Notification | None:
    return session.scalar(
        select(Notification).where(
            Notification.user_id == user_id,
            Notification.target_type == target_type,
            Notification.target_id == target_id,
        )
    )


def _apply_creation_update(
    record: Notification,
    *,
    type: NotificationType,
    title_key: str,
    payload: dict[str, Any],
    bump_unread: bool,
) -> None:
    record.type = type
    record.title_key = title_key
    record.payload_json = dict(payload)
    record.updated_at = utcnow()
    if bump_unread:
        record.read_at = None


def _publish(record: Notification) -> None:
    """Best-effort live push over the per-user SSE channel.

    Mirrors `NotificationResponse`'s shape so the frontend can reuse the same
    rendering code for a stream frame as for a polled list item. Fires
    alongside `_dispatch_push` rather than gating on the caller's eventual
    commit — same rationale as `publisher.publish_job_event`.
    """
    publisher.publish_notification(
        record.user_id,
        {
            "id": record.id,
            "type": record.type,
            "title_key": record.title_key,
            "payload": record.payload_json,
            "target_type": record.target_type,
            "target_id": record.target_id,
            "read": record.read_at is not None,
            "created_at": record.created_at.isoformat(),
            "updated_at": record.updated_at.isoformat(),
        },
    )


def _dispatch_push(
    session: Session, *, user_id: str, title_key: str, payload: dict[str, Any]
) -> None:
    tokens = session.scalars(select(Device.push_token).where(Device.user_id == user_id)).all()
    for token in tokens:
        send_push(token, title_key=title_key, payload=payload)


def send_push(push_token: str, *, title_key: str, payload: dict[str, Any]) -> None:
    """真正打进 APNs 的那一下。当前是占位实现——生产环境要换成真实 HTTP/2 请求。"""
    logger.info("push_stub token=%s title_key=%s payload=%s", push_token, title_key, payload)
