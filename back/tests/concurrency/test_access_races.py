"""Concurrent unlocks must debit the buyer exactly once."""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.domain.access import service as access_service
from app.domain.credits import service as credits
from app.domain.errors import Conflict, InsufficientCredits
from app.models import AccessGrant, CreditLedgerEntry
from app.models.enums import AccessSubjectType, LedgerEntryType
from tests.concurrency.conftest import race, run_in_parallel
from tests.conftest import make_user
from tests.factories import make_work

SessionFactory = Callable[[], Session]


def _is_expected_loss(outcome: object) -> bool:
    return isinstance(outcome, Conflict | InsufficientCredits | SQLAlchemyError | DBAPIError)


def test_two_unlocks_debit_the_buyer_once(sessions: SessionFactory) -> None:
    setup = sessions()
    seller = make_user(setup, email="seller@example.com", handle="seller")
    buyer = make_user(setup, email="buyer@example.com", handle="buyer")
    credits.grant(setup, buyer.id, 100, idempotency_key=f"seed:{buyer.id}")
    work, _ = make_work(setup, seller, access_credits=10)
    setup.commit()

    def unlock(session: Session) -> str:
        grant = access_service.unlock_work(session, buyer_user_id=buyer.id, work_id=work.id)
        assert grant is not None
        return grant.id

    outcomes = run_in_parallel([race(unlock, sessions), race(unlock, sessions)])
    winners = [o for o in outcomes if not isinstance(o, BaseException)]
    losers = [o for o in outcomes if isinstance(o, BaseException)]

    assert len(winners) >= 1, f"expected at least one grant, got {outcomes}"
    assert all(grant_id == winners[0] for grant_id in winners)
    if losers:
        assert _is_expected_loss(losers[0]), losers[0]

    check = sessions()
    grants = list(
        check.scalars(
            select(AccessGrant).where(
                AccessGrant.buyer_user_id == buyer.id,
                AccessGrant.subject_type == AccessSubjectType.WORK.value,
                AccessGrant.subject_id == work.id,
            )
        )
    )
    assert len(grants) == 1
    assert grants[0].price_credits == 10
    assert grants[0].seller_net_credits == 9
    assert grants[0].platform_fee_credits == 1

    buyer_account = credits.get_account(check, buyer.id)
    seller_account = credits.get_account(check, seller.id)
    assert buyer_account.available_balance == 90
    assert seller_account.available_balance == 9
    assert (
        check.scalar(
            select(func.count())
            .select_from(CreditLedgerEntry)
            .where(
                CreditLedgerEntry.account_id == buyer_account.id,
                CreditLedgerEntry.type == LedgerEntryType.ACCESS_OUT,
            )
        )
        == 1
    )
    assert (
        check.scalar(
            select(func.count())
            .select_from(CreditLedgerEntry)
            .where(
                CreditLedgerEntry.account_id == seller_account.id,
                CreditLedgerEntry.type == LedgerEntryType.ACCESS_IN,
            )
        )
        == 1
    )
