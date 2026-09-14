"""Credit accounts and the append-only ledger.

Every mutation is a conditional UPDATE guarded by the account's `version`
column plus a uniquely-constrained ledger row. That combination is what makes
the four required invariants hold under concurrency:

1. A job is captured at most once.
2. A reserve always ends in exactly one capture or one release.
3. A payment event books credits at most once.
4. Balances never go negative.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

from sqlalchemy import ColumnElement, case, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import rows_affected
from app.domain.errors import (
    Conflict,
    InsufficientCredits,
    NotFound,
    ReasonRequired,
    SpendLimitExceeded,
)
from app.models import CreditAccount, CreditLedgerEntry
from app.models.base import utcnow
from app.models.enums import LedgerEntryType

SIGNUP_GRANT_CREDITS = 200


@dataclass(slots=True)
class LedgerResult:
    entry: CreditLedgerEntry
    available_balance: int
    reserved_balance: int


@dataclass(slots=True, frozen=True)
class BillingLedgerRow:
    """One consumer-visible billing line. Not a stored ledger row.

    A job's reserve is folded with its later capture or release so the
    billing page shows one lifecycle record. The append-only table is
    unchanged; do not persist this projection.
    """

    id: str
    type: LedgerEntryType
    amount: int
    balance_after: int
    job_id: str | None
    reason: str | None
    created_at: dt.datetime


_SETTLEMENT_TYPES = (LedgerEntryType.CAPTURE, LedgerEntryType.RELEASE)


def get_or_create_account(session: Session, user_id: str) -> CreditAccount:
    account = session.scalar(select(CreditAccount).where(CreditAccount.user_id == user_id))
    if account is None:
        account = CreditAccount(user_id=user_id, available_balance=0, reserved_balance=0)
        session.add(account)
        session.flush()
    return account


def get_account(session: Session, user_id: str) -> CreditAccount:
    account = session.scalar(select(CreditAccount).where(CreditAccount.user_id == user_id))
    if account is None:
        raise NotFound("积分账户不存在。")
    return account


def current_spend_period(now: dt.datetime | None = None) -> str:
    """The UTC calendar month a reserve counts toward, as "YYYY-MM"."""
    return (now or utcnow()).astimezone(dt.UTC).strftime("%Y-%m")


def period_spent(account: CreditAccount, period: str) -> int:
    return account.period_spent if account.spend_period == period else 0


def remaining_monthly_spend(
    account: CreditAccount, *, now: dt.datetime | None = None
) -> int | None:
    """Credits the user may still reserve this month under their own cap;
    `None` when they set no cap."""
    if account.monthly_spend_limit is None:
        return None
    spent = period_spent(account, current_spend_period(now))
    return max(0, account.monthly_spend_limit - spent)


def set_monthly_spend_limit(session: Session, user_id: str, limit: int | None) -> CreditAccount:
    """The user's own setting, not a balance movement: a versioned
    conditional UPDATE like every other account write, but no ledger row.
    Lowering it below this month's spend only blocks further reserves."""
    if limit is not None and limit <= 0:
        raise Conflict("消费上限必须为正数。")
    account = get_or_create_account(session, user_id)
    expected_version = account.version
    matched = rows_affected(
        session,
        update(CreditAccount)
        .where(CreditAccount.id == account.id, CreditAccount.version == expected_version)
        .values(monthly_spend_limit=limit, version=expected_version + 1),
    )
    if matched != 1:
        raise Conflict("积分账户已被并发修改，请重试。")
    account.monthly_spend_limit = limit
    account.version = expected_version + 1
    return account


def _apply(
    session: Session,
    account: CreditAccount,
    *,
    available_delta: int,
    reserved_delta: int,
    entry_type: LedgerEntryType,
    amount: int,
    job_id: str | None = None,
    payment_reference: str | None = None,
    idempotency_key: str | None = None,
    reason: str | None = None,
    actor_user_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    created_at: dt.datetime | None = None,
    spend_delta: int = 0,
    spend_period: str | None = None,
) -> LedgerResult:
    """Applies one balance movement and records it.

    The UPDATE carries the account version and non-negativity in its WHERE
    clause, so a losing racer simply matches zero rows and is told to retry
    instead of silently overdrawing.

    `spend_delta` moves the month's spend for the monthly cap: positive on
    a reserve (the cap is part of the same WHERE), negative when that
    reserve is released or partly returned. A refund for a month that has
    already rolled over has nothing left to undo and is dropped.
    """
    expected_version = account.version
    new_available = account.available_balance + available_delta
    new_reserved = account.reserved_balance + reserved_delta

    if new_available < 0:
        raise InsufficientCredits()
    if new_reserved < 0:
        raise Conflict("预扣余额不足，无法释放。")

    conditions: list[ColumnElement[bool]] = [
        CreditAccount.id == account.id,
        CreditAccount.version == expected_version,
        CreditAccount.available_balance + available_delta >= 0,
        CreditAccount.reserved_balance + reserved_delta >= 0,
    ]
    values: dict[str, Any] = {
        "available_balance": CreditAccount.available_balance + available_delta,
        "reserved_balance": CreditAccount.reserved_balance + reserved_delta,
        "version": expected_version + 1,
    }
    same_period = spend_period is not None and account.spend_period == spend_period
    if spend_delta < 0 and not same_period:
        spend_delta = 0
    new_spent = account.period_spent
    if spend_delta and spend_period is not None:
        new_spent = max(0, (account.period_spent if same_period else 0) + spend_delta)
        limit = account.monthly_spend_limit
        if spend_delta > 0 and limit is not None and new_spent > limit:
            raise SpendLimitExceeded(
                f"本月消费上限 {limit} 积分，还可用 {max(0, limit - new_spent + spend_delta)}。",
                limit=limit,
                remaining=max(0, limit - new_spent + spend_delta),
            )
        spent_now = case(
            (CreditAccount.spend_period == spend_period, CreditAccount.period_spent), else_=0
        )
        if spend_delta > 0:
            conditions.append(
                or_(
                    CreditAccount.monthly_spend_limit.is_(None),
                    spent_now + spend_delta <= CreditAccount.monthly_spend_limit,
                )
            )
        else:
            conditions.append(CreditAccount.spend_period == spend_period)
        values["spend_period"] = spend_period
        values["period_spent"] = func.greatest(spent_now + spend_delta, 0)

    matched = rows_affected(
        session,
        update(CreditAccount).where(*conditions).values(**values),
    )
    if matched != 1:
        raise Conflict("积分账户已被并发修改，请重试。")

    entry = CreditLedgerEntry(
        account_id=account.id,
        type=entry_type,
        amount=amount,
        balance_after=new_available,
        reserved_after=new_reserved,
        job_id=job_id,
        payment_reference=payment_reference,
        idempotency_key=idempotency_key,
        reason=reason,
        actor_user_id=actor_user_id,
        metadata_json=metadata or {},
        created_at=created_at or utcnow(),
    )
    session.add(entry)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise Conflict("该账本记录已存在。") from exc

    account.available_balance = new_available
    account.reserved_balance = new_reserved
    account.version = expected_version + 1
    if spend_delta and spend_period is not None:
        account.spend_period = spend_period
        account.period_spent = new_spent
    return LedgerResult(entry=entry, available_balance=new_available, reserved_balance=new_reserved)


def grant(
    session: Session,
    user_id: str,
    amount: int,
    *,
    idempotency_key: str,
    metadata: dict[str, Any] | None = None,
) -> LedgerResult:
    """Free credits — the signup gift, a redemption code, an operator gift."""
    if amount <= 0:
        raise Conflict("赠送积分必须为正数。")
    account = get_or_create_account(session, user_id)
    return _apply(
        session,
        account,
        available_delta=amount,
        reserved_delta=0,
        entry_type=LedgerEntryType.GRANT,
        amount=amount,
        idempotency_key=idempotency_key,
        metadata=metadata,
    )


def purchase(
    session: Session,
    user_id: str,
    amount: int,
    *,
    payment_reference: str,
    metadata: dict[str, Any] | None = None,
) -> LedgerResult:
    """Books a settled payment.

    `payment_reference` is uniquely constrained, so re-delivering the same
    webhook can never credit the account twice.
    """
    if amount <= 0:
        raise Conflict("购买积分必须为正数。")
    account = get_or_create_account(session, user_id)
    return _apply(
        session,
        account,
        available_delta=amount,
        reserved_delta=0,
        entry_type=LedgerEntryType.PURCHASE,
        amount=amount,
        payment_reference=payment_reference,
        metadata=metadata,
    )


def reserve(session: Session, user_id: str, amount: int, *, job_id: str) -> LedgerResult:
    """Moves credits from available to reserved before generation starts."""
    if amount <= 0:
        raise Conflict("预扣积分必须为正数。")
    account = get_or_create_account(session, user_id)
    if account.available_balance < amount:
        raise InsufficientCredits()
    # The month is stamped on the reserve so its later release/capture
    # refunds the right month's spend (or nothing, once it has rolled over).
    period = current_spend_period()
    return _apply(
        session,
        account,
        available_delta=-amount,
        reserved_delta=amount,
        entry_type=LedgerEntryType.RESERVE,
        amount=-amount,
        job_id=job_id,
        metadata={"spend_period": period},
        spend_delta=amount,
        spend_period=period,
    )


def _reserve_period(reservation: CreditLedgerEntry) -> str | None:
    period = (reservation.metadata_json or {}).get("spend_period")
    return period if isinstance(period, str) else None


def capture(session: Session, user_id: str, *, job_id: str, actual_amount: int) -> LedgerResult:
    """Settles a reservation against real consumption.

    Any positive difference is returned to available in the same transaction,
    so an over-quote never silently keeps the user's credits locked.
    """
    account = get_account(session, user_id)
    reservation = _find_entry(session, account.id, job_id, LedgerEntryType.RESERVE)
    if reservation is None:
        raise Conflict("该任务没有预扣记录。")
    if _find_entry(session, account.id, job_id, LedgerEntryType.CAPTURE) is not None:
        raise Conflict("该任务已经结算过。")
    if _find_entry(session, account.id, job_id, LedgerEntryType.RELEASE) is not None:
        raise Conflict("该任务的预扣已释放，不能再结算。")

    reserved_amount = -reservation.amount
    if actual_amount < 0:
        raise Conflict("实际消耗不能为负。")
    # The provider must never bill above what we locked; clamping here keeps the
    # user's exposure equal to the quote they approved.
    settled = min(actual_amount, reserved_amount)
    refund = reserved_amount - settled

    return _apply(
        session,
        account,
        available_delta=refund,
        reserved_delta=-reserved_amount,
        entry_type=LedgerEntryType.CAPTURE,
        amount=-settled,
        job_id=job_id,
        metadata={"reserved": reserved_amount, "settled": settled, "returned": refund},
        spend_delta=-refund,
        spend_period=_reserve_period(reservation),
    )


def release(
    session: Session, user_id: str, *, job_id: str, reason: str | None = None
) -> LedgerResult:
    """Returns a reservation in full after failure, timeout or cancellation."""
    account = get_account(session, user_id)
    reservation = _find_entry(session, account.id, job_id, LedgerEntryType.RESERVE)
    if reservation is None:
        raise Conflict("该任务没有预扣记录。")
    if _find_entry(session, account.id, job_id, LedgerEntryType.RELEASE) is not None:
        raise Conflict("该任务的预扣已释放。")
    if _find_entry(session, account.id, job_id, LedgerEntryType.CAPTURE) is not None:
        raise Conflict("该任务已结算，不能释放。")

    reserved_amount = -reservation.amount
    return _apply(
        session,
        account,
        available_delta=reserved_amount,
        reserved_delta=-reserved_amount,
        entry_type=LedgerEntryType.RELEASE,
        amount=reserved_amount,
        job_id=job_id,
        reason=reason,
        spend_delta=-reserved_amount,
        spend_period=_reserve_period(reservation),
    )


def adjust(
    session: Session,
    user_id: str,
    amount: int,
    *,
    reason: str,
    actor_user_id: str,
    idempotency_key: str,
) -> LedgerResult:
    """Manual back-office correction.

    History is never edited: a correction is a new append-only row that must
    carry an operator identity and a written reason.
    """
    if not reason.strip():
        raise ReasonRequired()
    if amount == 0:
        raise Conflict("调账金额不能为 0。")
    account = get_or_create_account(session, user_id)
    return _apply(
        session,
        account,
        available_delta=amount,
        reserved_delta=0,
        entry_type=LedgerEntryType.ADJUSTMENT,
        amount=amount,
        reason=reason,
        actor_user_id=actor_user_id,
        idempotency_key=idempotency_key,
    )


def royalty_transfer(
    session: Session,
    *,
    from_user_id: str,
    to_user_id: str,
    amount: int,
    work_version_id: str,
    idempotency_key: str,
) -> tuple[LedgerResult, LedgerResult] | None:
    """Pays an ancestor author when a descendant is published.

    Returns None when the payer cannot cover it: royalties are a bonus on top
    of publication, never a reason to block one. Both legs share a suffix of
    the same idempotency key so a retried publish cannot double-pay.
    """
    if amount <= 0 or from_user_id == to_user_id:
        return None

    payer = get_or_create_account(session, from_user_id)
    if payer.available_balance < amount:
        return None

    out_leg = _apply(
        session,
        payer,
        available_delta=-amount,
        reserved_delta=0,
        entry_type=LedgerEntryType.ROYALTY_OUT,
        amount=-amount,
        idempotency_key=f"{idempotency_key}:out:{to_user_id}",
        metadata={"work_version_id": work_version_id, "beneficiary_user_id": to_user_id},
    )
    payee = get_or_create_account(session, to_user_id)
    in_leg = _apply(
        session,
        payee,
        available_delta=amount,
        reserved_delta=0,
        entry_type=LedgerEntryType.ROYALTY_IN,
        amount=amount,
        idempotency_key=f"{idempotency_key}:in:{to_user_id}",
        metadata={"work_version_id": work_version_id, "payer_user_id": from_user_id},
    )
    return out_leg, in_leg


def access_transfer(
    session: Session,
    *,
    from_user_id: str,
    to_user_id: str,
    price: int,
    platform_fee: int,
    seller_net: int,
    idempotency_key: str,
    metadata: dict[str, Any] | None = None,
) -> tuple[LedgerResult, LedgerResult]:
    """Mandatory marketplace transfer. Unlike royalties, this must succeed.

    Buyer is charged `price`. Seller receives `seller_net`. The fee is burned
    (not booked to a platform account): `price == seller_net + platform_fee`.
    """
    if price <= 0:
        raise Conflict("解锁价格必须为正数。")
    if from_user_id == to_user_id:
        raise Conflict("不能向自己支付授权费。")
    if seller_net < 0 or platform_fee < 0 or seller_net + platform_fee != price:
        raise Conflict("授权费拆分不守恒。")

    extra = dict(metadata or {})
    payer = get_or_create_account(session, from_user_id)
    out_leg = _apply(
        session,
        payer,
        available_delta=-price,
        reserved_delta=0,
        entry_type=LedgerEntryType.ACCESS_OUT,
        amount=-price,
        idempotency_key=f"{idempotency_key}:out",
        metadata={**extra, "beneficiary_user_id": to_user_id, "source": "purchased"},
    )
    payee = get_or_create_account(session, to_user_id)
    in_leg = _apply(
        session,
        payee,
        available_delta=seller_net,
        reserved_delta=0,
        entry_type=LedgerEntryType.ACCESS_IN,
        amount=seller_net,
        idempotency_key=f"{idempotency_key}:in",
        metadata={
            **extra,
            "payer_user_id": from_user_id,
            "source": "earned",
            "platform_fee_credits": platform_fee,
        },
    )
    return out_leg, in_leg


def _find_entry(
    session: Session, account_id: str, job_id: str, entry_type: LedgerEntryType
) -> CreditLedgerEntry | None:
    return session.scalar(
        select(CreditLedgerEntry).where(
            CreditLedgerEntry.account_id == account_id,
            CreditLedgerEntry.job_id == job_id,
            CreditLedgerEntry.type == entry_type,
        )
    )


def list_ledger(
    session: Session, user_id: str, *, cursor: str | None = None, limit: int = 20
) -> list[CreditLedgerEntry]:
    account = get_account(session, user_id)
    stmt = (
        select(CreditLedgerEntry)
        .where(CreditLedgerEntry.account_id == account.id)
        .order_by(CreditLedgerEntry.created_at.desc(), CreditLedgerEntry.id.desc())
        .limit(limit)
    )
    if cursor:
        stmt = stmt.where(CreditLedgerEntry.id < cursor)
    return list(session.scalars(stmt))


def _as_billing_row(entry: CreditLedgerEntry) -> BillingLedgerRow:
    return BillingLedgerRow(
        id=entry.id,
        type=LedgerEntryType(entry.type),
        amount=entry.amount,
        balance_after=entry.balance_after,
        job_id=entry.job_id,
        reason=entry.reason,
        created_at=entry.created_at,
    )


def _project_reserve(
    reserve: CreditLedgerEntry, settlement: CreditLedgerEntry | None
) -> BillingLedgerRow:
    if settlement is None:
        return _as_billing_row(reserve)
    if settlement.type == LedgerEntryType.CAPTURE:
        return BillingLedgerRow(
            id=reserve.id,
            type=LedgerEntryType.CAPTURE,
            amount=settlement.amount,
            balance_after=settlement.balance_after,
            job_id=reserve.job_id,
            reason=settlement.reason or reserve.reason,
            created_at=reserve.created_at,
        )
    return BillingLedgerRow(
        id=reserve.id,
        type=LedgerEntryType.RELEASE,
        amount=0,
        balance_after=settlement.balance_after,
        job_id=reserve.job_id,
        reason=settlement.reason or reserve.reason,
        created_at=reserve.created_at,
    )


def list_billing_history(
    session: Session, user_id: str, *, cursor: str | None = None, limit: int = 20
) -> list[BillingLedgerRow]:
    """Consumer billing history: one visible row per job lifecycle.

    Stored `capture` / `release` rows are omitted; an open reserve stays a
    hold, a captured reserve becomes a settlement (actual charge), and a
    released reserve becomes a zero-amount release. Admin and reconciliation
    keep reading the raw ledger via `list_ledger`.
    """
    account = get_account(session, user_id)
    stmt = (
        select(CreditLedgerEntry)
        .where(
            CreditLedgerEntry.account_id == account.id,
            CreditLedgerEntry.type.notin_(_SETTLEMENT_TYPES),
        )
        .order_by(CreditLedgerEntry.created_at.desc(), CreditLedgerEntry.id.desc())
        .limit(limit)
    )
    if cursor:
        stmt = stmt.where(CreditLedgerEntry.id < cursor)
    rows = list(session.scalars(stmt))

    job_ids = [row.job_id for row in rows if row.type == LedgerEntryType.RESERVE and row.job_id]
    settlements_by_job: dict[str, CreditLedgerEntry] = {}
    if job_ids:
        for settlement in session.scalars(
            select(CreditLedgerEntry).where(
                CreditLedgerEntry.account_id == account.id,
                CreditLedgerEntry.job_id.in_(job_ids),
                CreditLedgerEntry.type.in_(_SETTLEMENT_TYPES),
            )
        ):
            if settlement.job_id is not None:
                settlements_by_job[settlement.job_id] = settlement

    projected: list[BillingLedgerRow] = []
    for row in rows:
        if row.type == LedgerEntryType.RESERVE and row.job_id:
            projected.append(_project_reserve(row, settlements_by_job.get(row.job_id)))
        else:
            projected.append(_as_billing_row(row))
    return projected
