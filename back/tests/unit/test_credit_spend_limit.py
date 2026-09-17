"""The user's own monthly spend cap on the credit ledger.

A reserve counts toward the month it was made in; its release, or the part a
capture returns, gives that month's spend back — unless the month has
already rolled over, in which case there is nothing to undo.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.credits import service as credits
from app.domain.errors import SpendLimitExceeded
from app.domain.jobs import service as jobs_service
from app.models import CreditLedgerEntry, User
from app.models.enums import Operation
from tests.factories import make_job


def _funded(db: Session, user: User, balance: int = 1_000) -> None:
    credits.grant(db, user.id, balance, idempotency_key=f"grant:{user.id}")


def test_no_cap_means_no_limit(db: Session, author: User) -> None:
    _funded(db, author)
    credits.reserve(db, author.id, 900, job_id=make_job(db, author).id)
    account = credits.get_account(db, author.id)
    assert credits.remaining_monthly_spend(account) is None
    assert account.period_spent == 900


def test_a_reserve_over_the_cap_is_refused_and_changes_nothing(db: Session, author: User) -> None:
    _funded(db, author)
    credits.set_monthly_spend_limit(db, author.id, 100)
    credits.reserve(db, author.id, 60, job_id=make_job(db, author).id)

    with pytest.raises(SpendLimitExceeded):
        credits.reserve(db, author.id, 50, job_id=make_job(db, author).id)

    account = credits.get_account(db, author.id)
    assert account.available_balance == 940
    assert account.period_spent == 60
    assert credits.remaining_monthly_spend(account) == 40


def test_release_and_capture_give_the_months_spend_back(db: Session, author: User) -> None:
    _funded(db, author)
    credits.set_monthly_spend_limit(db, author.id, 100)
    released = make_job(db, author)
    credits.reserve(db, author.id, 60, job_id=released.id)
    credits.release(db, author.id, job_id=released.id)
    assert credits.get_account(db, author.id).period_spent == 0

    captured = make_job(db, author)
    credits.reserve(db, author.id, 80, job_id=captured.id)
    credits.capture(db, author.id, job_id=captured.id, actual_amount=50)
    account = credits.get_account(db, author.id)
    assert account.period_spent == 50
    assert credits.remaining_monthly_spend(account) == 50


def test_a_new_month_starts_from_zero_and_last_months_refund_is_dropped(
    db: Session, author: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    _funded(db, author)
    credits.set_monthly_spend_limit(db, author.id, 100)
    monkeypatch.setattr(credits, "current_spend_period", lambda now=None: "2026-08")
    august = make_job(db, author)
    credits.reserve(db, author.id, 90, job_id=august.id)

    monkeypatch.setattr(credits, "current_spend_period", lambda now=None: "2026-09")
    credits.reserve(db, author.id, 90, job_id=make_job(db, author).id)
    credits.release(db, author.id, job_id=august.id)

    account = credits.get_account(db, author.id)
    assert account.spend_period == "2026-09"
    assert account.period_spent == 90


def test_setting_the_cap_bumps_the_version_and_writes_no_ledger_row(
    db: Session, author: User
) -> None:
    _funded(db, author)
    before = credits.get_account(db, author.id).version
    rows = db.scalar(select(func.count()).select_from(CreditLedgerEntry))

    account = credits.set_monthly_spend_limit(db, author.id, 500)
    assert (account.monthly_spend_limit, account.version) == (500, before + 1)
    cleared = credits.set_monthly_spend_limit(db, author.id, None)
    assert cleared.monthly_spend_limit is None
    assert db.scalar(select(func.count()).select_from(CreditLedgerEntry)) == rows


def test_submit_refuses_an_over_cap_job_before_it_exists(db: Session, author: User) -> None:
    _funded(db, author)
    credits.set_monthly_spend_limit(db, author.id, 1)

    with pytest.raises(SpendLimitExceeded):
        jobs_service.submit(
            db,
            user_id=author.id,
            operation=Operation.TEXT_TO_IMAGE,
            quality_tier="standard",
            params={"prompt": "雨夜的街道", "aspect_ratio": "1:1", "duration_seconds": 0},
            idempotency_key="spend-cap-submit",
        )
    assert credits.get_account(db, author.id).reserved_balance == 0
