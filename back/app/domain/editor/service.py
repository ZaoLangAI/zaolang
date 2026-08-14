"""Ownership, revisions, plans and variants for the drama editor."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.editor import commands as command_codec
from app.domain.editor import document as docs
from app.domain.editor import flags as editor_flags
from app.domain.editor import leases as lease_service
from app.domain.editor import state_machine
from app.domain.editor.time import ticks_from_ms
from app.domain.errors import (
    Forbidden,
    NotFound,
    RevisionConflict,
    ValidationFailed,
)
from app.models import (
    Asset,
    CutRevision,
    DeliveryVariant,
    DramaEpisode,
    EditorCommandEvent,
    EditorLease,
    EditorOperationEvent,
    EditPlan,
    EpisodeCut,
    GenerationJob,
    Series,
)
from app.models.base import new_id, utcnow
from app.models.enums import (
    DeliveryVariantStatus,
    DramaEpisodeStatus,
    EditorCommandEventStatus,
    EditPlanStatus,
    EpisodeCutKind,
    EpisodeCutStatus,
    JobStatus,
    SeriesKind,
    SeriesStatus,
)
from app.platform_config import service as config_service
from app.platform_config.schemas import ShortformConfig
from app.realtime import publisher


def _owned_series(session: Session, *, user_id: str, series_id: str) -> Series:
    series = session.get(Series, series_id)
    if series is None or series.owner_user_id != user_id:
        raise NotFound("剧集不存在。")
    return series


def _owned_episode(session: Session, *, user_id: str, episode_id: str) -> DramaEpisode:
    episode = session.get(DramaEpisode, episode_id)
    if episode is None:
        raise NotFound("剧集分集不存在。")
    _owned_series(session, user_id=user_id, series_id=episode.series_id)
    return episode


def _owned_cut(session: Session, *, user_id: str, cut_id: str) -> EpisodeCut:
    cut = session.get(EpisodeCut, cut_id)
    if cut is None:
        raise NotFound("剪辑不存在。")
    _owned_episode(session, user_id=user_id, episode_id=cut.episode_id)
    return cut


def require_drama_series(session: Session, *, user_id: str, series_id: str) -> Series:
    series = _owned_series(session, user_id=user_id, series_id=series_id)
    if series.kind != SeriesKind.DRAMA:
        raise ValidationFailed("该系列不是短剧制作项目。")
    return series


def create_drama_series(
    session: Session,
    *,
    user_id: str,
    title: str,
    description: str | None = None,
    default_locale: str = "zh-CN",
    shortform_profile_key: str | None = None,
    allow_external_models: bool = False,
) -> Series:
    editor_flags.require_flag(session, editor_flags.FLAG_DRAMA, user_id=user_id)
    series = Series(
        owner_user_id=user_id,
        title=title.strip(),
        description=(description or "").strip() or None,
        shortform_profile_key=shortform_profile_key,
        character_ids_json=[],
        kind=SeriesKind.DRAMA,
        default_locale=default_locale,
        status=SeriesStatus.ACTIVE,
        allow_external_models=allow_external_models,
    )
    session.add(series)
    session.flush()
    return series


def list_drama_series(session: Session, *, user_id: str) -> list[Series]:
    editor_flags.require_flag(session, editor_flags.FLAG_DRAMA, user_id=user_id)
    stmt = (
        select(Series)
        .where(Series.owner_user_id == user_id, Series.kind == SeriesKind.DRAMA)
        .order_by(Series.created_at.desc())
    )
    return list(session.scalars(stmt))


def create_episode(
    session: Session,
    *,
    user_id: str,
    series_id: str,
    title: str,
    episode_number: int | None = None,
    synopsis: str | None = None,
) -> DramaEpisode:
    editor_flags.require_flag(session, editor_flags.FLAG_DRAMA, user_id=user_id)
    series = require_drama_series(session, user_id=user_id, series_id=series_id)
    number = episode_number
    if number is None:
        current = session.scalars(
            select(DramaEpisode.episode_number)
            .where(DramaEpisode.series_id == series.id)
            .order_by(DramaEpisode.episode_number.desc())
        ).first()
        number = int(current or 0) + 1
    existing = session.scalar(
        select(DramaEpisode).where(
            DramaEpisode.series_id == series.id, DramaEpisode.episode_number == number
        )
    )
    if existing is not None:
        raise ValidationFailed("该集数已存在。")
    episode = DramaEpisode(
        series_id=series.id,
        episode_number=number,
        title=title.strip(),
        synopsis=(synopsis or "").strip() or None,
        script_json={},
        status=DramaEpisodeStatus.DRAFT,
    )
    session.add(episode)
    session.flush()
    return episode


def list_episodes(session: Session, *, user_id: str, series_id: str) -> list[DramaEpisode]:
    editor_flags.require_flag(session, editor_flags.FLAG_DRAMA, user_id=user_id)
    series = require_drama_series(session, user_id=user_id, series_id=series_id)
    stmt = (
        select(DramaEpisode)
        .where(DramaEpisode.series_id == series.id)
        .order_by(DramaEpisode.episode_number.asc())
    )
    return list(session.scalars(stmt))


def list_cuts(session: Session, *, user_id: str, episode_id: str) -> list[EpisodeCut]:
    editor_flags.require_flag(session, editor_flags.FLAG_EDITOR, user_id=user_id)
    episode = _owned_episode(session, user_id=user_id, episode_id=episode_id)
    stmt = (
        select(EpisodeCut)
        .where(EpisodeCut.episode_id == episode.id)
        .order_by(EpisodeCut.created_at.desc())
    )
    return list(session.scalars(stmt))


def create_cut_from_job(
    session: Session,
    *,
    user_id: str,
    job_id: str,
    series_id: str | None = None,
    title: str | None = None,
) -> tuple[EpisodeCut, CutRevision]:
    editor_flags.require_flag(session, editor_flags.FLAG_EDITOR, user_id=user_id)
    job = session.get(GenerationJob, job_id)
    if job is None or job.user_id != user_id:
        raise NotFound("生成任务不存在。")
    if job.status != JobStatus.SUCCEEDED or not job.output_asset_id:
        raise ValidationFailed("只有成功且带成片的任务才能进入剪辑。")
    if series_id:
        series = require_drama_series(session, user_id=user_id, series_id=series_id)
    else:
        existing = session.scalars(
            select(Series)
            .where(Series.owner_user_id == user_id, Series.kind == SeriesKind.DRAMA)
            .order_by(Series.created_at.desc())
        ).first()
        series = existing or create_drama_series(
            session, user_id=user_id, title=(title or "短剧").strip() or "短剧"
        )
    episode = create_episode(
        session,
        user_id=user_id,
        series_id=series.id,
        title=(title or "新一集").strip() or "新一集",
    )
    return create_cut_from_asset(
        session,
        user_id=user_id,
        episode_id=episode.id,
        asset_id=job.output_asset_id,
        job_id=job.id,
    )


def create_cut_from_asset(
    session: Session,
    *,
    user_id: str,
    episode_id: str,
    asset_id: str,
    name: str = "主剪辑",
    kind: str = EpisodeCutKind.FULL,
    job_id: str | None = None,
) -> tuple[EpisodeCut, CutRevision]:
    editor_flags.require_flag(session, editor_flags.FLAG_EDITOR, user_id=user_id)
    episode = _owned_episode(session, user_id=user_id, episode_id=episode_id)
    asset = session.get(Asset, asset_id)
    if asset is None or asset.owner_user_id != user_id:
        raise Forbidden("不能使用他人的素材作为剪辑源。")
    if job_id:
        job = session.get(GenerationJob, job_id)
        if job is None or job.user_id != user_id or job.output_asset_id != asset_id:
            raise ValidationFailed("生成任务与素材不匹配。")
    cut = EpisodeCut(
        episode_id=episode.id,
        kind=kind,
        name=name.strip() or "主剪辑",
        status=EpisodeCutStatus.DRAFT,
        source_asset_id=asset.id,
        source_job_id=job_id,
    )
    session.add(cut)
    session.flush()
    duration = ticks_from_ms(asset.duration_ms)
    canvas_w = asset.width or 1080
    canvas_h = asset.height or 1920
    document = docs.empty_document(width=canvas_w, height=canvas_h)
    batch = {
        "schema_version": 1,
        "batch_id": new_id("bat"),
        "expected_revision_id": None,
        "commands": [
            {
                "type": "insert_clip",
                "track_id": "trk_video",
                "asset_id": asset.id,
                "at_ticks": 0,
                "duration_ticks": duration,
                "source_in_ticks": 0,
            }
        ],
    }
    validated = command_codec.validate_batch(batch)
    applied = command_codec.apply_batch(document, validated["commands"], known_assets={asset.id})
    bindings = [{"asset_id": asset.id, "role": "source", "duration_ticks": duration}]
    revision = _persist_revision(
        session,
        cut=cut,
        parent=None,
        document=applied,
        bindings=bindings,
        user_id=user_id,
        command_summary={"source": "create_cut", "commands": validated["commands"]},
    )
    cut.head_revision_id = revision.id
    cut.status = EpisodeCutStatus.EDITING
    session.flush()
    return cut, revision


def acquire_lease(
    session: Session,
    *,
    user_id: str,
    cut_id: str,
    browser_instance_id: str,
) -> tuple[EditorLease, str]:
    editor_flags.require_flag(session, editor_flags.FLAG_EDITOR, user_id=user_id)
    cut = _owned_cut(session, user_id=user_id, cut_id=cut_id)
    return lease_service.acquire(
        session, cut=cut, user_id=user_id, browser_instance_id=browser_instance_id
    )


def apply_commands(
    session: Session,
    *,
    user_id: str,
    cut_id: str,
    lease_id: str,
    lease_token: str,
    payload: dict[str, Any],
) -> CutRevision:
    editor_flags.require_flag(session, editor_flags.FLAG_EDITOR, user_id=user_id)
    cut = _owned_cut(session, user_id=user_id, cut_id=cut_id)
    # Locks the cut row for the rest of this transaction so two concurrent
    # writers computing the same next revision_no can't both pass the CAS
    # check in Python; the loser blocks here instead of racing the unique
    # constraint on cut_revisions(cut_id, revision_no).
    cut = session.get(EpisodeCut, cut.id, with_for_update=True) or cut
    lease = lease_service.require_write_lease(
        session, cut_id=cut.id, user_id=user_id, lease_id=lease_id, token=lease_token
    )
    batch = command_codec.validate_batch(
        {
            "schema_version": payload.get("schema_version"),
            "batch_id": payload.get("batch_id"),
            "expected_revision_id": payload.get("expected_revision_id"),
            "commands": payload.get("commands"),
        }
    )
    head = session.get(CutRevision, cut.head_revision_id) if cut.head_revision_id else None
    expected = batch["expected_revision_id"]
    if expected != (head.id if head else None):
        raise RevisionConflict()
    document = docs.clone_document(head.document_json) if head else docs.empty_document()
    known = {str(item.get("asset_id")) for item in (head.asset_bindings_json if head else [])}
    known |= {
        str(command.get("asset_id")) for command in batch["commands"] if command.get("asset_id")
    }
    _assert_assets_owned(session, user_id=user_id, asset_ids=known)
    applied = command_codec.apply_batch(document, batch["commands"], known_assets=known)
    bindings = _bindings_from_document(applied)
    try:
        revision = _persist_revision(
            session,
            cut=cut,
            parent=head,
            document=applied,
            bindings=bindings,
            user_id=user_id,
            command_summary={"batch_id": batch["batch_id"], "commands": batch["commands"]},
        )
    except IntegrityError as error:
        session.rollback()
        raise RevisionConflict() from error
    if cut.head_revision_id != (head.id if head else None):
        raise RevisionConflict()
    cut.head_revision_id = revision.id
    lease.last_sequence += 1
    lease.base_revision_id = revision.id
    event = EditorCommandEvent(
        lease_id=lease.id,
        sequence=lease.last_sequence,
        batch_id=batch["batch_id"],
        expected_revision_id=expected,
        result_revision_id=revision.id,
        commands_json=batch["commands"],
        status=EditorCommandEventStatus.APPLIED,
        created_at=utcnow(),
    )
    session.add(event)
    session.flush()
    return revision


def head_revision(session: Session, cut: EpisodeCut) -> CutRevision | None:
    if not cut.head_revision_id:
        return None
    return session.get(CutRevision, cut.head_revision_id)


def create_variants(
    session: Session,
    *,
    user_id: str,
    revision_id: str,
    profile_keys: list[str],
    caption_language: str | None = None,
    caption_mode: str = "burned",
    format: str = "mp4",
) -> list[DeliveryVariant]:
    editor_flags.require_flag(session, editor_flags.FLAG_EXPORT, user_id=user_id)
    revision = session.get(CutRevision, revision_id)
    if revision is None:
        raise NotFound("修订不存在。")
    cut = _owned_cut(session, user_id=user_id, cut_id=revision.cut_id)
    del cut
    cfg = config_service.get_typed(session, "shortform", ShortformConfig)
    created: list[DeliveryVariant] = []
    for key in profile_keys:
        profile = cfg.profiles.get(key)
        if profile is None:
            raise ValidationFailed(f"未知交付规格: {key}。")
        spec = {
            "profile_key": key,
            "aspect_ratio": profile.aspect_ratio,
            "width": profile.width,
            "height": profile.height,
            "fps_num": 30,
            "fps_den": 1,
            "format": format,
            "caption_language": caption_language,
            "caption_mode": caption_mode,
            "max_duration_ticks": profile.max_duration_seconds * 120_000,
        }
        digest = hashlib.sha256(
            json.dumps(spec, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        existing = session.scalar(
            select(DeliveryVariant).where(
                DeliveryVariant.cut_revision_id == revision.id,
                DeliveryVariant.spec_hash == digest,
            )
        )
        if existing is not None:
            created.append(existing)
            continue
        variant = DeliveryVariant(
            cut_revision_id=revision.id,
            profile_key=key,
            aspect_ratio=profile.aspect_ratio,
            width=profile.width,
            height=profile.height,
            fps_num=30,
            fps_den=1,
            format=format,
            caption_language=caption_language,
            caption_mode=caption_mode,
            spec_json=spec,
            spec_hash=digest,
            status=DeliveryVariantStatus.READY,
        )
        session.add(variant)
        session.flush()
        created.append(variant)
    return created


def append_operation_event(
    session: Session,
    operation_id: str,
    *,
    event_type: str,
    status: str,
    public_message: str,
    progress: int = 0,
    payload: dict[str, Any] | None = None,
    now: dt.datetime | None = None,
) -> EditorOperationEvent:
    current_max = session.scalar(
        select(EditorOperationEvent.sequence)
        .where(EditorOperationEvent.operation_id == operation_id)
        .order_by(EditorOperationEvent.sequence.desc())
        .limit(1)
    )
    event = EditorOperationEvent(
        operation_id=operation_id,
        sequence=(current_max or 0) + 1,
        event_type=event_type,
        status=status,
        progress=max(0, min(100, progress)),
        public_message=public_message,
        payload_json=payload or {},
        created_at=now or utcnow(),
    )
    session.add(event)
    session.flush()
    publisher.publish_job_event(
        operation_id,
        {
            "sequence": event.sequence,
            "event_type": event.event_type,
            "status": event.status,
            "progress": event.progress,
            "message": event.public_message,
        },
    )
    return event


def events_since(session: Session, operation_id: str, after: int) -> list[EditorOperationEvent]:
    stmt = (
        select(EditorOperationEvent)
        .where(
            EditorOperationEvent.operation_id == operation_id,
            EditorOperationEvent.sequence > after,
        )
        .order_by(EditorOperationEvent.sequence.asc())
    )
    return list(session.scalars(stmt))


def create_edit_plan(
    session: Session,
    *,
    user_id: str,
    cut_id: str,
    goal: str,
    commands: list[dict[str, Any]] | None = None,
    summary: str | None = None,
    agent_run_id: str | None = None,
    model: str | None = None,
    warnings: list[str] | None = None,
) -> EditPlan:
    editor_flags.require_flag(session, editor_flags.FLAG_AI, user_id=user_id)
    cut = _owned_cut(session, user_id=user_id, cut_id=cut_id)
    head = head_revision(session, cut)
    if head is None:
        raise ValidationFailed("剪辑还没有可编辑的修订。")
    plan = EditPlan(
        cut_id=cut.id,
        base_revision_id=head.id,
        status=EditPlanStatus.VALIDATED,
        summary=summary or goal.strip()[:240],
        commands_json=commands or [],
        warnings_json=warnings or [],
        agent_run_id=agent_run_id,
        model=model,
        prompt_slot="timeline_edit_plan",
        expires_at=utcnow() + dt.timedelta(hours=6),
        created_by_user_id=user_id,
    )
    if commands:
        try:
            validated = command_codec.validate_batch(
                {
                    "schema_version": 1,
                    "batch_id": new_id("bat"),
                    "expected_revision_id": head.id,
                    "commands": commands,
                }
            )
            preview = command_codec.apply_batch(
                docs.clone_document(head.document_json),
                validated["commands"],
                known_assets={str(item.get("asset_id")) for item in head.asset_bindings_json},
            )
            plan.commands_json = validated["commands"]
            plan.diff_json = {
                "base_duration_ticks": head.duration_ticks,
                "result_duration_ticks": docs.duration_ticks(preview),
            }
            plan.validation_json = {"ok": True}
        except Exception as exc:
            plan.status = EditPlanStatus.FAILED
            plan.validation_json = {"ok": False, "error": str(exc)}
    else:
        plan.validation_json = {"ok": True, "empty": True}
    session.add(plan)
    session.flush()
    return plan


def apply_edit_plan(
    session: Session,
    *,
    user_id: str,
    plan_id: str,
    lease_id: str,
    lease_token: str,
    selected_indexes: list[int] | None = None,
) -> CutRevision:
    plan = session.get(EditPlan, plan_id)
    if plan is None:
        raise NotFound("剪辑方案不存在。")
    commands = list(plan.commands_json)
    if selected_indexes is not None:
        commands = [commands[i] for i in selected_indexes if 0 <= i < len(commands)]
    revision = apply_commands(
        session,
        user_id=user_id,
        cut_id=plan.cut_id,
        lease_id=lease_id,
        lease_token=lease_token,
        payload={
            "schema_version": 1,
            "batch_id": new_id("bat"),
            "expected_revision_id": plan.base_revision_id,
            "commands": commands,
        },
    )
    state_machine.transition_plan(session, plan.id, EditPlanStatus.APPLIED)
    plan.applied_revision_id = revision.id
    session.flush()
    return revision


def reject_edit_plan(session: Session, *, user_id: str, plan_id: str) -> EditPlan:
    plan = session.get(EditPlan, plan_id)
    if plan is None:
        raise NotFound("剪辑方案不存在。")
    _owned_cut(session, user_id=user_id, cut_id=plan.cut_id)
    return state_machine.transition_plan(session, plan.id, EditPlanStatus.REJECTED)


def _persist_revision(
    session: Session,
    *,
    cut: EpisodeCut,
    parent: CutRevision | None,
    document: dict[str, Any],
    bindings: list[dict[str, Any]],
    user_id: str,
    command_summary: dict[str, Any],
) -> CutRevision:
    digest = docs.content_hash(document, bindings)
    revision_no = (parent.revision_no + 1) if parent else 1
    existing = session.scalar(
        select(CutRevision).where(CutRevision.cut_id == cut.id, CutRevision.content_hash == digest)
    )
    if existing is not None:
        return existing
    revision = CutRevision(
        cut_id=cut.id,
        revision_no=revision_no,
        parent_revision_id=parent.id if parent else None,
        engine="zaolang-canonical",
        engine_schema_version=1,
        document_json=docs.canonicalize(document),
        asset_bindings_json=bindings,
        duration_ticks=docs.duration_ticks(document),
        content_hash=digest,
        command_summary_json=command_summary,
        created_by_user_id=user_id,
        created_at=utcnow(),
    )
    session.add(revision)
    session.flush()
    return revision


def _bindings_from_document(document: dict[str, Any]) -> list[dict[str, Any]]:
    bindings: list[dict[str, Any]] = []
    seen: set[str] = set()
    for element in docs.iter_elements(document):
        asset_id = element.get("asset_id")
        if not asset_id or asset_id in seen:
            continue
        seen.add(str(asset_id))
        bindings.append(
            {
                "asset_id": asset_id,
                "role": "source" if element.get("type") == "clip" else "caption",
                "duration_ticks": element.get("duration_ticks"),
            }
        )
    overlay = document.get("brand_overlay") or {}
    if overlay.get("asset_id"):
        bindings.append({"asset_id": overlay["asset_id"], "role": "brand", "duration_ticks": None})
    return bindings


def _assert_assets_owned(session: Session, *, user_id: str, asset_ids: set[str]) -> None:
    ids = [asset_id for asset_id in asset_ids if asset_id]
    if not ids:
        return
    rows = list(session.scalars(select(Asset).where(Asset.id.in_(ids))))
    owned = {row.id for row in rows if row.owner_user_id == user_id}
    missing = set(ids) - owned
    if missing:
        raise Forbidden("命令引用了无权使用的素材。")
