"""Content operations: review queue, reports, tombstones, duplicate detection."""

from __future__ import annotations

import datetime as dt
from typing import Any

from fastapi import APIRouter, Query, Request
from sqlalchemy import func, literal, or_, select

from app.api.deps import DbSession
from app.api.request_utils import as_utc
from app.api.schemas.admin import (
    AppealAdminView,
    AppealDecisionRequest,
    CreationSkillAdminView,
    FingerprintDuplicateGroup,
    ModerationDecisionRequest,
    ModerationHistoryEntry,
    ModerationJobDetailView,
    ModerationQueueView,
    ModerationSubjectDetailView,
    ModerationWorkDetailView,
    ReportCaseView,
    ReportResolveRequest,
    TombstoneRequest,
)
from app.api.schemas.common import OkResponse, Page
from app.api.v1.admin.deps import (
    AdminDangerous,
    AdminRead,
    AdminWrite,
    Operator,
    Reviewer,
    Viewer,
    require_confirmation,
)
from app.domain.audit import service as audit
from app.domain.errors import Conflict, NotFound, ValidationFailed
from app.domain.moderation_queue import service as moderation_queue
from app.domain.notifications import push as notifications
from app.domain.publishing import service as publishing
from app.domain.skill_library import service as skill_library
from app.models import (
    Asset,
    ContentFingerprint,
    CreationSkill,
    GenerationJob,
    ModerationQueueItem,
    ModerationResult,
    Profile,
    ReportCase,
    Work,
    WorkAppeal,
    WorkVersion,
)
from app.models.base import utcnow
from app.models.enums import (
    AppealStatus,
    JobOrigin,
    JobStatus,
    LifecycleStatus,
    MediaType,
    ModerationStage,
    ModerationStatus,
    NotificationType,
    Operation,
    ReportStatus,
)
from app.presenters import media_urls

_CREATIVE_MEDIA_TYPES = (MediaType.IMAGE.value, MediaType.VIDEO.value, MediaType.AUDIO.value)

router = APIRouter(tags=["admin:content"])


@router.get("/moderation/queue", response_model=Page[ModerationQueueView])
def moderation_queue_list(
    session: DbSession,
    user: Viewer,
    _: AdminRead,
    status: str | None = None,
    creator: str | None = None,
    title: str | None = None,
    media_type: str | None = None,
    created_after: dt.datetime | None = None,
    created_before: dt.datetime | None = None,
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> Page[ModerationQueueView]:
    """Published creative works, newest first.

    The cursor is the work id, same shape as the jobs console: ids are
    lexically time-ordered, so `id < cursor` pages without skipping when
    something is inserted above the current page.
    """
    stmt = (
        select(Work)
        .join(WorkVersion, WorkVersion.id == Work.current_version_id)
        .outerjoin(Asset, Asset.id == WorkVersion.primary_output_asset_id)
        .where(Work.published_at.is_not(None))
        .order_by(Work.published_at.desc(), Work.id.desc())
    )
    requested_types = _parse_media_types(media_type) if media_type else None
    if requested_types:
        stmt = stmt.where(Asset.media_type.in_(requested_types))
    else:
        stmt = stmt.where(
            or_(
                Asset.media_type.in_(_CREATIVE_MEDIA_TYPES),
                WorkVersion.primary_output_asset_id.is_(None),
            )
        )
    if status:
        stmt = stmt.where(_derived_work_status().in_(_parse_moderation_statuses(status)))
    if creator:
        stmt = stmt.where(_creator_match(creator))
    if title:
        stmt = stmt.where(WorkVersion.title.ilike(f"%{title}%"))
    if created_after:
        stmt = stmt.where(Work.published_at >= as_utc(created_after))
    if created_before:
        stmt = stmt.where(Work.published_at <= as_utc(created_before))
    if cursor:
        stmt = stmt.where(Work.id < cursor)

    rows = list(session.scalars(stmt.limit(limit + 1)))
    has_more = len(rows) > limit
    page = rows[:limit]
    return Page(
        items=[_work_list_view(session, work) for work in page],
        next_cursor=page[-1].id if has_more and page else None,
        has_more=has_more,
    )


@router.get("/moderation/queue/{item_id}/detail", response_model=ModerationSubjectDetailView)
def moderation_detail(
    item_id: str, session: DbSession, user: Viewer, _: AdminRead
) -> ModerationSubjectDetailView:
    """The queue row plus its full verdict trail, so a reviewer can see what
    already happened to this subject before deciding whether to reverse it.

    `item_id` may be a queue row or a published work id (works Safety
    auto-approved never got a queue row).
    """
    item, work = _resolve_subject(session, item_id)
    subject_type = item.subject_type if item is not None else "work"
    subject_id = item.subject_id if item is not None else work.id  # type: ignore[union-attr]
    history_stmt = (
        select(ModerationResult)
        .where(
            ModerationResult.subject_type == subject_type,
            ModerationResult.subject_id == subject_id,
        )
        .order_by(ModerationResult.created_at.desc())
    )
    history = [
        ModerationHistoryEntry(
            id=row.id,
            stage=row.stage,
            status=ModerationStatus(row.status),
            decided_by=row.decided_by,
            reviewer_user_id=row.reviewer_user_id,
            reason_code=row.reason_code,
            categories=row.categories_json.get("categories", []),
            public_message=row.public_message,
            created_at=row.created_at,
        )
        for row in session.scalars(history_stmt)
    ]

    work_detail = None
    skill_detail = None
    job_detail = None
    if subject_type == "work":
        work_detail = _work_detail_view(session, subject_id)
    elif item is not None and item.subject_type == "skill":
        skill = session.get(CreationSkill, item.subject_id)
        if skill is not None:
            skill_detail = CreationSkillAdminView(
                id=skill.id,
                owner_user_id=skill.owner_user_id,
                title=skill.title,
                description=skill.description,
                category=skill.category,
                cover_url=media_urls.asset_url(session, skill.cover_asset_id),
                cover_media_type=media_urls.media_type_of(session, skill.cover_asset_id),
                applicable_operations=[
                    Operation(value) for value in skill.applicable_operations_json
                ],
                visibility=skill.visibility,
                status=skill.status,
                usage_count=skill.usage_count,
                reject_reason=skill.reject_reason,
                created_at=skill.created_at,
            )
    elif item is not None and item.subject_type == "generation_job":
        job_detail = _job_detail_view(session, item.subject_id)

    queue_view = (
        _queue_view(session, item) if item is not None else _work_as_queue_view(session, work)
    )
    return ModerationSubjectDetailView(
        queue_item=queue_view,
        history=history,
        work=work_detail,
        skill=skill_detail,
        job=job_detail,
        open_report_count=moderation_queue.open_report_count(
            session, subject_type=subject_type, subject_id=subject_id
        ),
    )


@router.post("/moderation/queue/{item_id}/claim", response_model=ModerationQueueView)
def claim(item_id: str, session: DbSession, user: Reviewer, _: AdminWrite) -> ModerationQueueView:
    """Assigns an item so two reviewers do not duplicate work."""
    item = _queue_item(session, item_id)
    if item.claimed_by_user_id is not None and item.claimed_by_user_id != user.id:
        raise Conflict("该审核项已被其他审核员认领。")
    item.claimed_by_user_id = user.id
    session.commit()
    return _queue_view(session, item)


@router.post("/moderation/queue/{item_id}/decide", response_model=ModerationQueueView)
def decide(
    item_id: str,
    payload: ModerationDecisionRequest,
    request: Request,
    session: DbSession,
    user: Reviewer,
    _: AdminWrite,
) -> ModerationQueueView:
    """Records a human verdict.

    The agent's original verdict is never edited: a reviewer adds a new
    `ModerationResult` row that supersedes it, so the disagreement stays on the
    record.
    """
    item = _queue_item(session, item_id, create_for_work=True)
    before = {"status": item.status}

    session.add(
        ModerationResult(
            stage=item.stage,
            subject_type=item.subject_type,
            subject_id=item.subject_id,
            status=payload.decision,
            categories_json={},
            reason_code=payload.reason_code,
            public_message=payload.public_message,
            decided_by="human",
            reviewer_user_id=user.id,
            created_at=utcnow(),
        )
    )
    item.status = payload.decision
    item.reason_code = payload.reason_code
    item.resolved_at = utcnow()

    if item.subject_type == "work":
        _apply_work_decision(session, item.subject_id, payload, reviewer_user_id=user.id)
    elif item.subject_type == "skill":
        _apply_skill_decision(session, item.subject_id, payload, reviewer_user_id=user.id)

    audit.record(
        session,
        actor=user,
        action="moderation.decide",
        target_type=item.subject_type,
        target_id=item.subject_id,
        before=before,
        after={"status": item.status, "reason_code": item.reason_code},
        reason=payload.note,
        request=request,
    )
    session.commit()
    return _queue_view(session, item)


@router.get("/reports", response_model=Page[ReportCaseView])
def list_reports(
    session: DbSession,
    user: Viewer,
    _: AdminRead,
    status: str | None = None,
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> Page[ReportCaseView]:
    """Oldest first, so a report cannot age out of view behind newer ones.

    `id` alone is enough of a cursor: ids are lexically time-ordered, so it
    sorts consistently with `created_at` without needing a composite key.
    """
    stmt = (
        select(ReportCase)
        .where(ReportCase.status == (status or ReportStatus.OPEN))
        .order_by(ReportCase.id)
    )
    if cursor:
        stmt = stmt.where(ReportCase.id > cursor)

    rows = list(session.scalars(stmt.limit(limit + 1)))
    has_more = len(rows) > limit
    page = rows[:limit]

    return Page(
        items=[_report_view(session, r) for r in page],
        next_cursor=page[-1].id if has_more and page else None,
        has_more=has_more,
    )


@router.post("/reports/{report_id}/resolve", response_model=ReportCaseView)
def resolve_report(
    report_id: str,
    payload: ReportResolveRequest,
    request: Request,
    session: DbSession,
    user: Reviewer,
    _: AdminWrite,
) -> ReportCaseView:
    report = session.get(ReportCase, report_id)
    if report is None:
        raise NotFound("举报记录不存在。")

    before = {"status": report.status}
    report.status = {
        "resolved": ReportStatus.UPHELD,
        "rejected": ReportStatus.DISMISSED,
        "escalated": ReportStatus.IN_REVIEW,
    }[payload.status]
    report.resolution_note = payload.resolution_note
    report.handled_by_user_id = user.id
    report.handled_at = utcnow()

    audit.record(
        session,
        actor=user,
        action="report.resolve",
        target_type="report_case",
        target_id=report.id,
        before=before,
        after={"status": report.status},
        reason=payload.resolution_note,
        request=request,
    )
    session.commit()
    return _report_view(session, report)


@router.get("/appeals", response_model=Page[AppealAdminView])
def list_appeals(
    session: DbSession,
    user: Viewer,
    _: AdminRead,
    status: str | None = None,
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> Page[AppealAdminView]:
    """Oldest first, same cursor shape as `list_reports`."""
    stmt = (
        select(WorkAppeal)
        .where(WorkAppeal.status == (status or AppealStatus.PENDING))
        .order_by(WorkAppeal.id)
    )
    if cursor:
        stmt = stmt.where(WorkAppeal.id > cursor)

    rows = list(session.scalars(stmt.limit(limit + 1)))
    has_more = len(rows) > limit
    page = rows[:limit]

    return Page(
        items=[_appeal_view(session, a) for a in page],
        next_cursor=page[-1].id if has_more and page else None,
        has_more=has_more,
    )


@router.post("/appeals/{appeal_id}/decide", response_model=AppealAdminView)
def decide_appeal(
    appeal_id: str,
    payload: AppealDecisionRequest,
    request: Request,
    session: DbSession,
    user: Reviewer,
    _: AdminWrite,
) -> AppealAdminView:
    """Grant restores the work (see `publishing.restore`); deny leaves it
    hidden. Both notify the owner and require a `decision_note`."""
    appeal = session.get(WorkAppeal, appeal_id)
    if appeal is None:
        raise NotFound("申诉记录不存在。")
    if appeal.status != AppealStatus.PENDING:
        raise Conflict("该申诉已处理。")

    before = {"status": appeal.status}
    if payload.decision == "granted":
        publishing.restore(session, work_id=appeal.work_id)
        appeal.status = AppealStatus.GRANTED
        notify_title_key = "notification.appeal_granted"
        notify_payload: dict[str, Any] = {}
    else:
        appeal.status = AppealStatus.DENIED
        notify_title_key = "notification.appeal_denied"
        notify_payload = {"note": payload.decision_note}

    appeal.decision_note = payload.decision_note
    appeal.decided_by_user_id = user.id
    appeal.decided_at = utcnow()

    _notify(
        session,
        user_id=appeal.owner_user_id,
        title_key=notify_title_key,
        payload=notify_payload,
        target_type="work",
        target_id=appeal.work_id,
    )

    audit.record(
        session,
        actor=user,
        action="appeal.decide",
        target_type="work_appeal",
        target_id=appeal.id,
        before=before,
        after={"status": appeal.status},
        reason=payload.decision_note,
        request=request,
    )
    session.commit()
    return _appeal_view(session, appeal)


@router.post("/works/{work_id}/tombstone", response_model=OkResponse)
def tombstone_work(
    work_id: str,
    payload: TombstoneRequest,
    request: Request,
    session: DbSession,
    user: Operator,
    __: AdminDangerous,
) -> OkResponse:
    """Removes a work from circulation without breaking descendant lineage."""
    require_confirmation(payload.confirm)
    work = session.get(Work, work_id)
    if work is None:
        raise NotFound("作品不存在。")

    before = {"lifecycle_status": work.lifecycle_status, "visibility": work.visibility}
    publishing.tombstone(session, work_id=work_id, reason=payload.reason, actor_user_id=user.id)
    _notify(
        session,
        user_id=work.owner_user_id,
        title_key="notification.work_tombstoned",
        payload={"reason": payload.reason},
        target_type="work",
        target_id=work_id,
    )
    audit.record(
        session,
        actor=user,
        action="work.tombstone",
        target_type="work",
        target_id=work_id,
        before=before,
        after={"lifecycle_status": LifecycleStatus.TOMBSTONE},
        reason=payload.reason,
        request=request,
    )
    session.commit()
    return OkResponse()


@router.post("/works/{work_id}/hide", response_model=OkResponse)
def hide_work(
    work_id: str,
    payload: TombstoneRequest,
    request: Request,
    session: DbSession,
    user: Reviewer,
    __: AdminDangerous,
) -> OkResponse:
    """Reversible removal from discovery, unlike a tombstone."""
    require_confirmation(payload.confirm)
    work = session.get(Work, work_id)
    if work is None:
        raise NotFound("作品不存在。")

    before = {"lifecycle_status": work.lifecycle_status}
    publishing.hide(session, work_id=work_id, reason=payload.reason, actor_user_id=user.id)
    _notify(
        session,
        user_id=work.owner_user_id,
        title_key="notification.work_hidden",
        payload={"reason": payload.reason},
        target_type="work",
        target_id=work_id,
    )
    audit.record(
        session,
        actor=user,
        action="work.hide",
        target_type="work",
        target_id=work_id,
        before=before,
        after={"lifecycle_status": LifecycleStatus.HIDDEN},
        reason=payload.reason,
        request=request,
    )
    session.commit()
    return OkResponse()


@router.post("/works/{work_id}/restore", response_model=OkResponse)
def restore_work(
    work_id: str, request: Request, session: DbSession, user: Operator, _: AdminWrite
) -> OkResponse:
    """Undoes a hide. A tombstone is final and cannot be restored here."""
    work = session.get(Work, work_id)
    if work is None:
        raise NotFound("作品不存在。")

    before = {"lifecycle_status": work.lifecycle_status}
    publishing.restore(session, work_id=work_id)
    _notify(
        session,
        user_id=work.owner_user_id,
        title_key="notification.work_restored",
        payload={},
        target_type="work",
        target_id=work_id,
    )
    audit.record(
        session,
        actor=user,
        action="work.restore",
        target_type="work",
        target_id=work_id,
        before=before,
        after={"lifecycle_status": LifecycleStatus.ACTIVE},
        request=request,
    )
    session.commit()
    return OkResponse()


@router.get("/fingerprints/duplicates", response_model=Page[FingerprintDuplicateGroup])
def duplicates(
    session: DbSession, user: Viewer, _: AdminRead, limit: int = Query(default=50, ge=1, le=200)
) -> Page[FingerprintDuplicateGroup]:
    """Assets sharing an identical perceptual hash.

    Exact matches only. Near-duplicate scanning by Hamming distance is a
    separate, heavier job and is not run from a request handler.
    """
    grouped = session.execute(
        select(
            ContentFingerprint.fingerprint_hex,
            func.count().label("total"),
            func.min(ContentFingerprint.created_at).label("first_seen"),
        )
        .group_by(ContentFingerprint.fingerprint_hex)
        .having(func.count() > 1)
        .order_by(func.count().desc())
        .limit(limit)
    ).all()

    items = []
    for fingerprint_hex, _total, first_seen in grouped:
        asset_ids = list(
            session.scalars(
                select(ContentFingerprint.asset_id).where(
                    ContentFingerprint.fingerprint_hex == fingerprint_hex
                )
            )
        )
        owners = list(session.scalars(select(Asset.owner_user_id).where(Asset.id.in_(asset_ids))))
        items.append(
            FingerprintDuplicateGroup(
                fingerprint=fingerprint_hex,
                asset_ids=asset_ids,
                owner_user_ids=sorted(set(owners)),
                first_seen_at=first_seen,
            )
        )
    return Page(items=items)


def _queue_item(  # type: ignore[no-untyped-def]
    session, item_id: str, *, create_for_work: bool = False
) -> ModerationQueueItem:
    item = session.get(ModerationQueueItem, item_id)
    if item is not None:
        return item
    work = session.get(Work, item_id)
    if work is None:
        raise NotFound("审核项不存在。")
    existing = moderation_queue.latest_work_queue_item(session, work.id)
    if existing is not None:
        return existing
    if create_for_work:
        return moderation_queue.ensure_work_queue_item(session, work_id=work.id)
    raise NotFound("审核项不存在。")


def _resolve_subject(  # type: ignore[no-untyped-def]
    session, item_id: str
) -> tuple[ModerationQueueItem | None, Work | None]:
    item = session.get(ModerationQueueItem, item_id)
    if item is not None:
        work = session.get(Work, item.subject_id) if item.subject_type == "work" else None
        return item, work
    work = session.get(Work, item_id)
    if work is None:
        raise NotFound("审核项不存在。")
    return moderation_queue.latest_work_queue_item(session, work.id), work


def _queue_view(session, item: ModerationQueueItem) -> ModerationQueueView:  # type: ignore[no-untyped-def]
    title: str | None = None
    preview: str | None = None
    preview_media_type: str | None = None
    owner_display_name: str | None = None
    owner_handle: str | None = None
    if item.subject_type == "work":
        work = session.get(Work, item.subject_id)
        if work is not None:
            return _work_as_queue_view(session, work, item)
    elif item.subject_type == "asset":
        preview = media_urls.asset_url(session, item.subject_id)
        preview_media_type = (
            media_urls.media_type_of(session, item.subject_id).value
            if media_urls.media_type_of(session, item.subject_id)
            else None
        )
    elif item.subject_type == "skill":
        skill = session.get(CreationSkill, item.subject_id)
        if skill is not None:
            title = skill.title
            preview = media_urls.asset_url(session, skill.cover_asset_id)
            owner_display_name, owner_handle = _owner_names(session, skill.owner_user_id)
    elif item.subject_type == "generation_job":
        job = session.get(GenerationJob, item.subject_id)
        if job is not None:
            prompt = str((job.request_json or {}).get("prompt") or "")
            title = prompt[:80] or job.id
            preview = media_urls.asset_url(session, job.output_asset_id)
            output_type = media_urls.media_type_of(session, job.output_asset_id)
            preview_media_type = output_type.value if output_type else None
            owner_display_name, owner_handle = _owner_names(session, job.user_id)

    return ModerationQueueView(
        id=item.id,
        subject_type=item.subject_type,
        subject_id=item.subject_id,
        stage=item.stage,
        status=ModerationStatus(item.status),
        priority=item.priority,
        reason_code=item.reason_code,
        claimed_by_user_id=item.claimed_by_user_id,
        preview_title=title,
        preview_url=preview,
        preview_media_type=preview_media_type,
        owner_display_name=owner_display_name,
        owner_handle=owner_handle,
        created_at=item.created_at,
    )


def _work_list_view(session, work: Work) -> ModerationQueueView:  # type: ignore[no-untyped-def]
    item = moderation_queue.latest_work_queue_item(session, work.id)
    return _work_as_queue_view(session, work, item)


def _work_as_queue_view(  # type: ignore[no-untyped-def]
    session, work: Work, item: ModerationQueueItem | None = None
) -> ModerationQueueView:
    version = session.get(WorkVersion, work.current_version_id or "")
    title = version.title if version else work.id
    preview, preview_media_type = _work_preview(session, version)
    owner_display_name, owner_handle = _owner_names(session, work.owner_user_id)
    result = None
    if item is None:
        result = session.scalar(
            select(ModerationResult)
            .where(
                ModerationResult.subject_type == "work",
                ModerationResult.subject_id == work.id,
            )
            .order_by(ModerationResult.created_at.desc(), ModerationResult.id.desc())
            .limit(1)
        )
    status = (
        ModerationStatus(item.status)
        if item is not None
        else ModerationStatus(result.status)
        if result is not None
        else ModerationStatus.APPROVED
    )
    return ModerationQueueView(
        id=item.id if item is not None else work.id,
        subject_type="work",
        subject_id=work.id,
        stage=item.stage if item is not None else ModerationStage.PRE_PUBLISH,
        status=status,
        priority=item.priority if item is not None else 0,
        reason_code=(
            item.reason_code if item is not None else (result.reason_code if result else None)
        ),
        claimed_by_user_id=item.claimed_by_user_id if item is not None else None,
        preview_title=title,
        preview_url=preview,
        preview_media_type=preview_media_type,
        owner_display_name=owner_display_name,
        owner_handle=owner_handle,
        created_at=item.created_at if item is not None else (work.published_at or work.created_at),
    )


def _work_preview(  # type: ignore[no-untyped-def]
    session, version: WorkVersion | None
) -> tuple[str | None, str | None]:
    if version is None:
        return None, None
    output_type = media_urls.media_type_of(session, version.primary_output_asset_id)
    cover_type = media_urls.media_type_of(session, version.cover_asset_id)
    media_type = output_type.value if output_type else (cover_type.value if cover_type else None)
    if cover_type == MediaType.IMAGE:
        return media_urls.asset_url(session, version.cover_asset_id), media_type
    if output_type == MediaType.VIDEO:
        return media_urls.asset_url(session, version.primary_output_asset_id), media_type
    if output_type == MediaType.AUDIO:
        return None, media_type
    preview_id = version.cover_asset_id or version.primary_output_asset_id
    return media_urls.asset_url(session, preview_id), media_type


def _owner_names(session, user_id: str) -> tuple[str | None, str | None]:  # type: ignore[no-untyped-def]
    profile = session.scalar(select(Profile).where(Profile.user_id == user_id))
    if profile is None:
        return None, None
    return profile.display_name, profile.handle


def _derived_work_status() -> Any:
    queue_status = (
        select(ModerationQueueItem.status)
        .where(
            ModerationQueueItem.subject_type == "work",
            ModerationQueueItem.subject_id == Work.id,
        )
        .order_by(ModerationQueueItem.created_at.desc(), ModerationQueueItem.id.desc())
        .limit(1)
        .scalar_subquery()
    )
    result_status = (
        select(ModerationResult.status)
        .where(
            ModerationResult.subject_type == "work",
            ModerationResult.subject_id == Work.id,
        )
        .order_by(ModerationResult.created_at.desc(), ModerationResult.id.desc())
        .limit(1)
        .scalar_subquery()
    )
    return func.coalesce(queue_status, result_status, literal(ModerationStatus.APPROVED.value))


def _parse_moderation_statuses(raw: str) -> list[str]:
    values = [part.strip() for part in raw.split(",") if part.strip()]
    known = {s.value for s in ModerationStatus}
    unknown = [v for v in values if v not in known]
    if unknown:
        raise ValidationFailed(f"未知的审核状态: {', '.join(unknown)}")
    return values


def _parse_media_types(raw: str) -> list[str]:
    values = [part.strip() for part in raw.split(",") if part.strip()]
    known = {s.value for s in MediaType}
    unknown = [v for v in values if v not in known]
    if unknown:
        raise ValidationFailed(f"未知的作品类型: {', '.join(unknown)}")
    return values


def _creator_match(needle: str) -> Any:
    needle_like = f"%{needle}%"
    return or_(
        Work.owner_user_id.ilike(needle_like),
        Work.owner_user_id.in_(
            select(Profile.user_id).where(
                or_(Profile.handle.ilike(needle_like), Profile.display_name.ilike(needle_like))
            )
        ),
    )


def _work_detail_view(session, work_id: str) -> ModerationWorkDetailView | None:  # type: ignore[no-untyped-def]
    work = session.get(Work, work_id)
    if work is None:
        return None
    version = session.get(WorkVersion, work.current_version_id or "")
    owner_display_name, owner_handle = _owner_names(session, work.owner_user_id)
    output_type = (
        media_urls.media_type_of(session, version.primary_output_asset_id) if version else None
    )
    return ModerationWorkDetailView(
        id=work.id,
        title=version.title if version else work.id,
        description=version.description if version else None,
        prompt=version.reusable_params_json.get("prompt") if version else None,
        cover_url=media_urls.asset_url(session, version.cover_asset_id) if version else None,
        media_url=(
            media_urls.asset_url(session, version.primary_output_asset_id) if version else None
        ),
        media_type=output_type.value if output_type else None,
        owner_user_id=work.owner_user_id,
        owner_display_name=owner_display_name,
        owner_handle=owner_handle,
        visibility=work.visibility,
        lifecycle_status=work.lifecycle_status,
        tombstone_reason=work.tombstone_reason,
        hide_reason=work.hide_reason,
        created_at=work.created_at,
    )


def _report_view(session, report: ReportCase) -> ReportCaseView:  # type: ignore[no-untyped-def]
    handled_by_display_name = None
    if report.handled_by_user_id:
        handled_by_display_name, _ = _owner_names(session, report.handled_by_user_id)
    subject = (
        _work_detail_view(session, report.subject_id) if report.subject_type == "work" else None
    )
    return ReportCaseView(
        id=report.id,
        reporter_user_id=report.reporter_user_id,
        subject_type=report.subject_type,
        subject_id=report.subject_id,
        reason=report.reason,
        detail=report.detail,
        status=report.status,
        resolution_note=report.resolution_note,
        handled_by_user_id=report.handled_by_user_id,
        handled_by_display_name=handled_by_display_name,
        handled_at=report.handled_at,
        subject=subject,
        open_report_count=moderation_queue.open_report_count(
            session, subject_type=report.subject_type, subject_id=report.subject_id
        ),
        created_at=report.created_at,
    )


def _appeal_view(session, appeal: WorkAppeal) -> AppealAdminView:  # type: ignore[no-untyped-def]
    owner_display_name, owner_handle = _owner_names(session, appeal.owner_user_id)
    decided_by_display_name = None
    if appeal.decided_by_user_id:
        decided_by_display_name, _ = _owner_names(session, appeal.decided_by_user_id)
    return AppealAdminView(
        id=appeal.id,
        work_id=appeal.work_id,
        owner_user_id=appeal.owner_user_id,
        owner_display_name=owner_display_name,
        owner_handle=owner_handle,
        reason=appeal.reason,
        status=appeal.status,
        decision_note=appeal.decision_note,
        decided_by_user_id=appeal.decided_by_user_id,
        decided_by_display_name=decided_by_display_name,
        decided_at=appeal.decided_at,
        source_report_id=appeal.source_report_id,
        subject=_work_detail_view(session, appeal.work_id),
        open_report_count=moderation_queue.open_report_count(
            session, subject_type="work", subject_id=appeal.work_id
        ),
        created_at=appeal.created_at,
    )


def _job_detail_view(session, job_id: str) -> ModerationJobDetailView | None:  # type: ignore[no-untyped-def]
    job = session.get(GenerationJob, job_id)
    if job is None:
        return None
    asset = session.get(Asset, job.output_asset_id) if job.output_asset_id else None
    return ModerationJobDetailView(
        id=job.id,
        origin=JobOrigin(job.origin) if job.origin else JobOrigin.USER,
        operation=job.operation,
        quality_tier=job.quality_tier,
        status=JobStatus(job.status),
        prompt=str((job.request_json or {}).get("prompt") or "") or None,
        preview_url=media_urls.asset_url(session, job.output_asset_id),
        mime_type=asset.mime_type if asset is not None else None,
        created_at=job.created_at,
    )


def _apply_work_decision(  # type: ignore[no-untyped-def]
    session, work_id: str, payload: ModerationDecisionRequest, *, reviewer_user_id: str
) -> None:
    work = session.get(Work, work_id)
    if work is None:
        return

    if payload.decision == ModerationStatus.REJECTED:
        # A rejection is a reviewer's judgement call, not an operator's final
        # verdict — hide (reversible) rather than tombstone (permanent). An
        # operator can still tombstone separately via `/works/{id}/tombstone`.
        publishing.hide(
            session,
            work_id=work_id,
            reason=payload.reason_code or "moderation_rejected",
            actor_user_id=reviewer_user_id,
        )
        _notify(
            session,
            user_id=work.owner_user_id,
            title_key="notification.work_hidden",
            payload={"reason": payload.public_message or payload.reason_code or ""},
            target_type="work",
            target_id=work_id,
        )
    elif payload.decision == ModerationStatus.APPROVED:
        if work.lifecycle_status == LifecycleStatus.HIDDEN:
            publishing.restore(session, work_id=work_id)
        _notify(
            session,
            user_id=work.owner_user_id,
            title_key="notification.work_approved",
            payload={},
            target_type="work",
            target_id=work_id,
        )


def _apply_skill_decision(  # type: ignore[no-untyped-def]
    session, skill_id: str, payload: ModerationDecisionRequest, *, reviewer_user_id: str
) -> None:
    skill = session.get(CreationSkill, skill_id)
    if skill is None:
        return
    if payload.decision == ModerationStatus.APPROVED:
        skill_library.approve(session, skill=skill, reviewer_user_id=reviewer_user_id)
        _notify(
            session,
            user_id=skill.owner_user_id,
            title_key="notification.skill_approved",
            payload={"title": skill.title},
            target_type="skill",
            target_id=skill.id,
        )
    elif payload.decision == ModerationStatus.REJECTED:
        reason = payload.public_message or payload.note or payload.reason_code or "内容未通过审核。"
        skill_library.reject(session, skill=skill, reviewer_user_id=reviewer_user_id, reason=reason)
        _notify(
            session,
            user_id=skill.owner_user_id,
            title_key="notification.skill_rejected",
            payload={"title": skill.title, "reason": reason},
            target_type="skill",
            target_id=skill.id,
        )


def _notify(  # type: ignore[no-untyped-def]
    session,
    *,
    user_id: str,
    title_key: str,
    payload: dict[str, Any],
    target_type: str,
    target_id: str,
) -> None:
    """Thin wrapper keeping every moderation notification on `MODERATION` and
    carrying only interpolation values — the client resolves `title_key` to
    localized text itself, so one write serves all three UI languages."""
    notifications.notify(
        session,
        user_id=user_id,
        type=NotificationType.MODERATION,
        title_key=title_key,
        payload=payload,
        target_type=target_type,
        target_id=target_id,
    )
