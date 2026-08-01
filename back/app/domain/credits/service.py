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

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import rows_affected
from app.domain.errors import Conflict, InsufficientCredits, NotFound, ReasonRequired
from app.models import CreditAccount, CreditLedgerEntry
from app.models.base import utcnow
from app.models.enums import LedgerEntryType

SIGNUP_GRANT_CREDITS = 200


@dataclass(slots=True)
class LedgerResult:
    entry: CreditLedgerEntry
    available_balance: int
    reserved_balance: int


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
) -> LedgerResult:
    """Applies one balance movement and records it.

    The UPDATE carries the account version and non-negativity in its WHERE
    clause, so a losing racer simply matches zero rows and is told to retry
    instead of silently overdrawing.
    """
    expected_version = account.version
    new_available = account.available_balance + available_delta
    new_reserved = account.reserved_balance + reserved_delta

    if new_available < 0:
        raise InsufficientCredits()
    if new_reserved < 0:
        raise Conflict("预扣余额不足，无法释放。")

    matched = rows_affected(
        session,
        update(CreditAccount)
        .where(
            CreditAccount.id == account.id,
            CreditAccount.version == expected_version,
            CreditAccount.available_balance + available_delta >= 0,
            CreditAccount.reserved_balance + reserved_delta >= 0,
        )
        .values(
            available_balance=CreditAccount.available_balance + available_delta,
            reserved_balance=CreditAccount.reserved_balance + reserved_delta,
            version=expected_version + 1,
        ),
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
    return LedgerResult(entry=entry, available_balance=new_available, reserved_balance=new_reserved)


def grant(session: Session, user_id: str, amount: int, *, idempotency_key: str) -> LedgerResult:
    """Free credits, e.g. the signup gift. Intended for preview-tier work."""
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
    return _apply(
        session,
        account,
        available_delta=-amount,
        reserved_delta=amount,
        entry_type=LedgerEntryType.RESERVE,
        amount=-amount,
        job_id=job_id,
    )


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
