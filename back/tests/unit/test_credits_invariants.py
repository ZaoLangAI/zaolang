"""Credit ledger invariants.

These are the checks the design document calls non-negotiable: no double
capture, no dangling reserve, no negative balance, no double-booked payment.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.credits import service as credits
from app.domain.errors import Conflict, InsufficientCredits, ReasonRequired
from app.models import CreditLedgerEntry, User
from app.models.enums import LedgerEntryType
from tests.factories import make_job


def test_grant_then_reserve_moves_credits_to_reserved(db: Session, author: User) -> None:
    credits.grant(db, author.id, 100, idempotency_key="grant-1")
    job = make_job(db, author, reserved=30)

    result = credits.reserve(db, author.id, 30, job_id=job.id)

    assert result.available_balance == 70
    assert result.reserved_balance == 30


def test_reserve_rejects_amount_above_available(db: Session, author: User) -> None:
    credits.grant(db, author.id, 20, idempotency_key="grant-1")
    job = make_job(db, author)

    with pytest.raises(InsufficientCredits):
        credits.reserve(db, author.id, 50, job_id=job.id)

    account = credits.get_account(db, author.id)
    assert account.available_balance == 20
    assert account.reserved_balance == 0


def test_capture_settles_and_returns_the_difference(db: Session, author: User) -> None:
    credits.grant(db, author.id, 100, idempotency_key="grant-1")
    job = make_job(db, author)
    credits.reserve(db, author.id, 40, job_id=job.id)

    result = credits.capture(db, author.id, job_id=job.id, actual_amount=25)

    # 100 - 40 reserved, then 15 of the reservation comes back.
    assert result.available_balance == 75
    assert result.reserved_balance == 0
    assert result.entry.metadata_json["returned"] == 15


def test_capture_never_bills_above_the_reservation(db: Session, author: User) -> None:
    """The user approved a quote; a provider overrun must not exceed it."""
    credits.grant(db, author.id, 100, idempotency_key="grant-1")
    job = make_job(db, author)
    credits.reserve(db, author.id, 40, job_id=job.id)

    result = credits.capture(db, author.id, job_id=job.id, actual_amount=999)

    assert result.available_balance == 60
    assert result.entry.metadata_json["settled"] == 40


def test_job_can_be_captured_only_once(db: Session, author: User) -> None:
    credits.grant(db, author.id, 100, idempotency_key="grant-1")
    job = make_job(db, author)
    credits.reserve(db, author.id, 40, job_id=job.id)
    credits.capture(db, author.id, job_id=job.id, actual_amount=40)

    with pytest.raises(Conflict):
        credits.capture(db, author.id, job_id=job.id, actual_amount=40)


def test_release_returns_the_full_reservation(db: Session, author: User) -> None:
    credits.grant(db, author.id, 100, idempotency_key="grant-1")
    job = make_job(db, author)
    credits.reserve(db, author.id, 40, job_id=job.id)

    result = credits.release(db, author.id, job_id=job.id, reason="provider_failed")

    assert result.available_balance == 100
    assert result.reserved_balance == 0


def test_release_after_capture_is_rejected(db: Session, author: User) -> None:
    credits.grant(db, author.id, 100, idempotency_key="grant-1")
    job = make_job(db, author)
    credits.reserve(db, author.id, 40, job_id=job.id)
    credits.capture(db, author.id, job_id=job.id, actual_amount=40)

    with pytest.raises(Conflict):
        credits.release(db, author.id, job_id=job.id)


def test_capture_after_release_is_rejected(db: Session, author: User) -> None:
    credits.grant(db, author.id, 100, idempotency_key="grant-1")
    job = make_job(db, author)
    credits.reserve(db, author.id, 40, job_id=job.id)
    credits.release(db, author.id, job_id=job.id)

    with pytest.raises(Conflict):
        credits.capture(db, author.id, job_id=job.id, actual_amount=40)


def test_reserve_always_settles_exactly_once(db: Session, author: User) -> None:
    """Every reserve is matched by exactly one capture or one release."""
    credits.grant(db, author.id, 500, idempotency_key="grant-1")
    jobs = [make_job(db, author) for _ in range(4)]
    for job in jobs:
        credits.reserve(db, author.id, 20, job_id=job.id)
    credits.capture(db, author.id, job_id=jobs[0].id, actual_amount=20)
    credits.capture(db, author.id, job_id=jobs[1].id, actual_amount=5)
    credits.release(db, author.id, job_id=jobs[2].id)
    credits.release(db, author.id, job_id=jobs[3].id)

    account = credits.get_account(db, author.id)
    counts = dict(
        db.execute(
            select(CreditLedgerEntry.type, func.count())
            .where(CreditLedgerEntry.account_id == account.id)
            .group_by(CreditLedgerEntry.type)
        ).all()
    )
    assert counts[LedgerEntryType.RESERVE.value] == 4
    assert counts[LedgerEntryType.CAPTURE.value] + counts[LedgerEntryType.RELEASE.value] == 4
    assert account.reserved_balance == 0


def test_ledger_sum_matches_the_account_balance(db: Session, author: User) -> None:
    """The account is a cache of the ledger; the two must never diverge.

    Reserve and release only move credits between the two buckets, so the
    identity is: money in, minus money captured, equals everything still held.
    """
    credits.grant(db, author.id, 300, idempotency_key="grant-1")
    job_a = make_job(db, author)
    job_b = make_job(db, author)
    credits.reserve(db, author.id, 100, job_id=job_a.id)
    credits.capture(db, author.id, job_id=job_a.id, actual_amount=60)
    credits.reserve(db, author.id, 50, job_id=job_b.id)

    account = credits.get_account(db, author.id)
    entries = list(
        db.scalars(
            select(CreditLedgerEntry)
            .where(CreditLedgerEntry.account_id == account.id)
            .order_by(CreditLedgerEntry.created_at, CreditLedgerEntry.id)
        )
    )
    inflow = sum(
        e.amount
        for e in entries
        if e.type
        in (
            LedgerEntryType.GRANT,
            LedgerEntryType.PURCHASE,
            LedgerEntryType.ADJUSTMENT,
            LedgerEntryType.ROYALTY_IN,
            LedgerEntryType.ROYALTY_OUT,
        )
    )
    captured = -sum(e.amount for e in entries if e.type == LedgerEntryType.CAPTURE)

    assert inflow - captured == account.available_balance + account.reserved_balance
    assert entries[-1].balance_after == account.available_balance
    assert entries[-1].reserved_after == account.reserved_balance


def test_payment_reference_cannot_be_booked_twice(db: Session, author: User) -> None:
    credits.purchase(db, author.id, 500, payment_reference="pi_test_1")

    with pytest.raises(Conflict):
        credits.purchase(db, author.id, 500, payment_reference="pi_test_1")


def test_manual_adjustment_requires_a_reason(db: Session, author: User, operator: User) -> None:
    with pytest.raises(ReasonRequired):
        credits.adjust(
            db, author.id, 50, reason="   ", actor_user_id=operator.id, idempotency_key="adj-1"
        )


def test_manual_adjustment_appends_rather_than_edits(
    db: Session, author: User, operator: User
) -> None:
    credits.grant(db, author.id, 100, idempotency_key="grant-1")

    credits.adjust(
        db,
        author.id,
        -30,
        reason="补偿回收：重复发放",
        actor_user_id=operator.id,
        idempotency_key="adj-1",
    )

    account = credits.get_account(db, author.id)
    entries = list(
        db.scalars(
            select(CreditLedgerEntry)
            .where(CreditLedgerEntry.account_id == account.id)
            .order_by(CreditLedgerEntry.created_at)
        )
    )
    assert len(entries) == 2
    assert entries[0].type == LedgerEntryType.GRANT
    assert entries[1].actor_user_id == operator.id
    assert account.available_balance == 70


def test_optimistic_version_advances_on_each_mutation(db: Session, author: User) -> None:
    account = credits.get_or_create_account(db, author.id)
    start = account.version

    credits.grant(db, author.id, 10, idempotency_key="grant-1")
    credits.grant(db, author.id, 10, idempotency_key="grant-2")

    assert credits.get_account(db, author.id).version == start + 2
