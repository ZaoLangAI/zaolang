"""Credit operations: ledger search, reconciliation, dangling reserves, adjustments."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request
from sqlalchemy import select

from app.api.deps import DbSession
from app.api.schemas.admin import (
    AdjustCreditsRequest,
    DanglingReserveView,
    LedgerEntryView,
    ReconciliationView,
)
from app.api.schemas.common import Page
from app.api.v1.admin.deps import (
    AdminDangerous,
    AdminRead,
    Operator,
    Viewer,
    require_confirmation,
)
from app.domain.audit import service as audit
from app.domain.credits import reconciliation
from app.domain.credits import service as credits_service
from app.domain.errors import NotFound
from app.models import CreditAccount, CreditLedgerEntry, GenerationJob, ReconciliationReport
from app.models.base import new_id, utcnow
from app.models.enums import LedgerEntryType

router = APIRouter(tags=["admin:credits"])

# A reservation older than this on a live job is worth an operator's attention
# even before the expiry sweep would touch it.
DANGLING_WARNING_HOURS = 2


@router.get("/credits/ledger", response_model=Page[LedgerEntryView])
def ledger(
    session: DbSession,
    user: Viewer,
    _: AdminRead,
    user_id: str | None = None,
    job_id: str | None = None,
    entry_type: LedgerEntryType | None = None,
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> Page[LedgerEntryView]:
    stmt = (
        select(CreditLedgerEntry, CreditAccount.user_id)
        .join(CreditAccount, CreditAccount.id == CreditLedgerEntry.account_id)
        .order_by(CreditLedgerEntry.created_at.desc(), CreditLedgerEntry.id.desc())
    )
    if user_id:
        stmt = stmt.where(CreditAccount.user_id == user_id)
    if job_id:
        stmt = stmt.where(CreditLedgerEntry.job_id == job_id)
    if entry_type:
        stmt = stmt.where(CreditLedgerEntry.type == entry_type)
    if cursor:
        stmt = stmt.where(CreditLedgerEntry.id < cursor)

    rows = session.execute(stmt.limit(limit + 1)).all()
    has_more = len(rows) > limit
    page = rows[:limit]
    return Page(
        items=[
            LedgerEntryView(
                id=entry.id,
                account_id=entry.account_id,
                user_id=owner_id,
                type=entry.type,
                amount=entry.amount,
                balance_after=entry.balance_after,
                reserved_after=entry.reserved_after,
                job_id=entry.job_id,
                reason=entry.reason,
                actor_user_id=entry.actor_user_id,
                created_at=entry.created_at,
            )
            for entry, owner_id in page
        ],
        next_cursor=page[-1][0].id if has_more and page else None,
        has_more=has_more,
    )


@router.get("/credits/reconciliation", response_model=ReconciliationView)
def latest_reconciliation(
    session: DbSession, user: Viewer, _: AdminRead, refresh: bool = False
) -> ReconciliationView:
    """The stored snapshot, or a fresh one on demand."""
    report = None
    if not refresh:
        report = session.scalar(
            select(ReconciliationReport).order_by(ReconciliationReport.generated_at.desc()).limit(1)
        )
    if report is None:
        report = reconciliation.build_report(session)
        session.commit()

    return ReconciliationView(
        generated_at=report.generated_at,
        account_count=report.account_count,
        mismatched_account_count=report.mismatched_account_count,
        dangling_reserved_count=report.dangling_reserved_count,
        details=report.details_json,
    )


@router.get("/credits/dangling", response_model=Page[DanglingReserveView])
def dangling_reserves(session: DbSession, user: Viewer, _: AdminRead) -> Page[DanglingReserveView]:
    """Reservations that never became a capture or a release.

    This is the direct read-out of the "a reserve always settles" invariant, so
    a non-empty list means a settlement path was missed somewhere.
    """
    reserved = session.execute(
        select(CreditLedgerEntry, CreditAccount.user_id)
        .join(CreditAccount, CreditAccount.id == CreditLedgerEntry.account_id)
        .where(
            CreditLedgerEntry.type == LedgerEntryType.RESERVE,
            CreditLedgerEntry.job_id.is_not(None),
        )
    ).all()

    settled = set(
        session.scalars(
            select(CreditLedgerEntry.job_id).where(
                CreditLedgerEntry.type.in_(
                    [LedgerEntryType.CAPTURE.value, LedgerEntryType.RELEASE.value]
                )
            )
        )
    )

    now = utcnow()
    items = []
    for entry, owner_id in reserved:
        if entry.job_id in settled:
            continue
        age_hours = (now - entry.created_at).total_seconds() / 3600
        if age_hours < DANGLING_WARNING_HOURS:
            continue
        job = session.get(GenerationJob, entry.job_id or "")
        items.append(
            DanglingReserveView(
                job_id=str(entry.job_id),
                user_id=owner_id,
                amount=-entry.amount,
                reserved_at=entry.created_at,
                age_hours=round(age_hours, 2),
                job_status=job.status if job else "missing",
            )
        )
    items.sort(key=lambda i: -i.age_hours)
    return Page(items=items)


@router.post("/users/{user_id}/credits/adjust", response_model=LedgerEntryView)
def adjust(
    user_id: str,
    payload: AdjustCreditsRequest,
    request: Request,
    session: DbSession,
    user: Operator,
    _: AdminDangerous,
) -> LedgerEntryView:
    """Manual correction.

    Nothing is ever edited: this appends an `adjustment` row carrying the
    operator's identity and reason, so the history stays reconstructible.
    """
    require_confirmation(payload.confirm)
    account = session.scalar(select(CreditAccount).where(CreditAccount.user_id == user_id))
    before = {
        "available": account.available_balance if account else 0,
        "reserved": account.reserved_balance if account else 0,
    }

    result = credits_service.adjust(
        session,
        user_id,
        payload.amount,
        reason=payload.reason,
        actor_user_id=user.id,
        idempotency_key=payload.idempotency_key or new_id("adj"),
    )
    audit.record(
        session,
        actor=user,
        action="credit.adjust",
        target_type="user",
        target_id=user_id,
        before=before,
        after={"available": result.available_balance, "reserved": result.reserved_balance},
        reason=payload.reason,
        request=request,
    )
    session.commit()

    return LedgerEntryView(
        id=result.entry.id,
        account_id=result.entry.account_id,
        user_id=user_id,
        type=result.entry.type,
        amount=result.entry.amount,
        balance_after=result.entry.balance_after,
        reserved_after=result.entry.reserved_after,
        job_id=result.entry.job_id,
        reason=result.entry.reason,
        actor_user_id=result.entry.actor_user_id,
        created_at=result.entry.created_at,
    )


@router.get("/users/{user_id}/credits", response_model=Page[LedgerEntryView])
def user_ledger(
    user_id: str,
    session: DbSession,
    user: Viewer,
    _: AdminRead,
    limit: int = Query(default=50, ge=1, le=200),
) -> Page[LedgerEntryView]:
    account = session.scalar(select(CreditAccount).where(CreditAccount.user_id == user_id))
    if account is None:
        raise NotFound("该用户还没有积分账户。")
    return ledger(session, user, None, user_id=user_id, limit=limit)
