"""Content operations: review queue, reports, tombstones, duplicate detection."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request
from sqlalchemy import func, select

from app.api.deps import DbSession
from app.api.schemas.admin import (
    CreationSkillAdminView,
    FingerprintDuplicateGroup,
    ModerationDecisionRequest,
    ModerationHistoryEntry,
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
from app.domain.errors import NotFound
from app.domain.notifications import push as notifications
from app.domain.publishing import service as publishing
from app.domain.skill_library import service as skill_library
from app.models import (
    Asset,
    ContentFingerprint,
    CreationSkill,
    ModerationQueueItem,
    ModerationResult,
    ReportCase,
    Work,
    WorkVersion,
)
from app.models.base import utcnow
from app.models.enums import (
    LifecycleStatus,
    ModerationStatus,
    NotificationType,
    ReportStatus,
)
from app.presenters import media_urls

router = APIRouter(tags=["admin:content"])


@router.get("/moderation/queue", response_model=Page[ModerationQueueView])
def moderation_queue(
    session: DbSession,
    user: Viewer,
    _: AdminRead,
    status: ModerationStatus | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> Page[ModerationQueueView]:
    """Highest priority first; ties broken by age so nothing starves."""
    stmt = (
        select(ModerationQueueItem)
        .order_by(ModerationQueueItem.priority.desc(), ModerationQueueItem.created_at)
        .limit(limit)
    )
    stmt = stmt.where(ModerationQueueItem.status == (status or ModerationStatus.NEEDS_REVIEW))
    return Page(items=[_queue_view(session, item) for item in session.scalars(stmt)])


@router.get("/moderation/queue/{item_id}/detail", response_model=ModerationSubjectDetailView)
def moderation_detail(
    item_id: str, session: DbSession, user: Viewer, _: AdminRead
) -> ModerationSubjectDetailView:
    """The queue row plus its full verdict trail, so a reviewer can see what
    already happened to this subject before deciding whether to reverse it."""
    item = _queue_item(session, item_id)
    history_stmt = (
        select(ModerationResult)
        .where(
            ModerationResult.subject_type == item.subject_type,
            ModerationResult.subject_id == item.subject_id,
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
            public_message=row.public_message,
            created_at=row.created_at,
        )
        for row in session.scalars(history_stmt)
    ]

    work_detail = None
    skill_detail = None
    if item.subject_type == "work":
        work_detail = _work_detail_view(session, item.subject_id)
    elif item.subject_type == "skill":
        skill = session.get(CreationSkill, item.subject_id)
        if skill is not None:
            skill_detail = CreationSkillAdminView(
                id=skill.id,
                owner_user_id=skill.owner_user_id,
                title=skill.title,
                description=skill.description,
                category=skill.category,
                cover_url=media_urls.asset_url(session, skill.cover_asset_id),
                visibility=skill.visibility,
                status=skill.status,
                usage_count=skill.usage_count,
                reject_reason=skill.reject_reason,
                created_at=skill.created_at,
            )

    return ModerationSubjectDetailView(
        queue_item=_queue_view(session, item),
        history=history,
        work=work_detail,
        skill=skill_detail,
    )


@router.post("/moderation/queue/{item_id}/claim", response_model=ModerationQueueView)
def claim(item_id: str, session: DbSession, user: Reviewer, _: AdminWrite) -> ModerationQueueView:
    """Assigns an item so two reviewers do not duplicate work."""
    item = _queue_item(session, item_id)
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
    item = _queue_item(session, item_id)
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
    limit: int = Query(default=50, ge=1, le=200),
) -> Page[ReportCaseView]:
    stmt = (
        select(ReportCase)
        .where(ReportCase.status == (status or ReportStatus.OPEN))
        .order_by(ReportCase.created_at)
        .limit(limit)
    )
    return Page(items=[ReportCaseView.model_validate(r) for r in session.scalars(stmt)])


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
    return ReportCaseView.model_validate(report)


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


def _queue_item(session, item_id: str) -> ModerationQueueItem:  # type: ignore[no-untyped-def]
    item = session.get(ModerationQueueItem, item_id)
    if item is None:
        raise NotFound("审核项不存在。")
    return item


def _queue_view(session, item: ModerationQueueItem) -> ModerationQueueView:  # type: ignore[no-untyped-def]
    title: str | None = None
    preview: str | None = None
    if item.subject_type == "work":
        work = session.get(Work, item.subject_id)
        version = session.get(WorkVersion, work.current_version_id or "") if work else None
        if version is not None:
            title = version.title
            preview = media_urls.asset_url(session, version.cover_asset_id)
    elif item.subject_type == "asset":
        preview = media_urls.asset_url(session, item.subject_id)
    elif item.subject_type == "skill":
        skill = session.get(CreationSkill, item.subject_id)
        if skill is not None:
            title = skill.title
            preview = media_urls.asset_url(session, skill.cover_asset_id)

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
        created_at=item.created_at,
    )


def _work_detail_view(session, work_id: str) -> ModerationWorkDetailView | None:  # type: ignore[no-untyped-def]
    work = session.get(Work, work_id)
    if work is None:
        return None
    version = session.get(WorkVersion, work.current_version_id or "")
    return ModerationWorkDetailView(
        id=work.id,
        title=version.title if version else work.id,
        description=version.description if version else None,
        prompt=version.reusable_params_json.get("prompt") if version else None,
        cover_url=media_urls.asset_url(session, version.cover_asset_id) if version else None,
        media_url=(
            media_urls.asset_url(session, version.primary_output_asset_id) if version else None
        ),
        owner_user_id=work.owner_user_id,
        visibility=work.visibility,
        lifecycle_status=work.lifecycle_status,
        tombstone_reason=work.tombstone_reason,
        created_at=work.created_at,
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
