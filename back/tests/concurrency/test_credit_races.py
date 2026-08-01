"""Races against the credit ledger.

The ledger's guarantees are all about what happens when two transactions try the
same thing at once, so testing them sequentially proves very little. Each test
here starts genuinely parallel transactions on separate connections and asserts
that exactly one wins.
"""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.domain.credits import service as credits
from app.domain.errors import Conflict, InsufficientCredits
from app.models import CreditAccount, CreditLedgerEntry, User
from app.models.enums import LedgerEntryType
from tests.concurrency.conftest import race, run_in_parallel
from tests.conftest import make_user
from tests.factories import make_job

SessionFactory = Callable[[], Session]


def _seed_account(session: Session, *, balance: int) -> User:
    user = make_user(session, email="racer@example.com", handle="racer")
    credits.grant(session, user.id, balance, idempotency_key=f"seed:{user.id}")
    session.commit()
    return user


def _is_expected_loss(outcome: object) -> bool:
    """A loser must fail for a concurrency reason, not an arbitrary one."""
    return isinstance(outcome, Conflict | InsufficientCredits | SQLAlchemyError | DBAPIError)


def test_two_reserves_cannot_spend_the_same_credits(sessions: SessionFactory) -> None:
    """The classic double-spend: one balance, two simultaneous reservations.

    With 100 credits and two 80-credit reservations, exactly one may succeed. If
    both did, the account would be overdrawn by 60.
    """
    setup = sessions()
    user = _seed_account(setup, balance=100)
    job_a = make_job(setup, user, reserved=80)
    job_b = make_job(setup, user, reserved=80)
    setup.commit()

    def reserve(job_id: str) -> Callable[[Session], int]:
        def work(session: Session) -> int:
            # Reading the balance before either writer commits is the
            # interleaving a naive check-then-update would get wrong.
            credits.get_account(session, user.id)
            return credits.reserve(session, user.id, 80, job_id=job_id).reserved_balance

        return work

    outcomes = run_in_parallel(
        [race(reserve(job_a.id), sessions), race(reserve(job_b.id), sessions)]
    )
    winners = [o for o in outcomes if not isinstance(o, BaseException)]
    losers = [o for o in outcomes if isinstance(o, BaseException)]

    assert len(winners) == 1, f"expected exactly one winner, got {outcomes}"
    assert _is_expected_loss(losers[0]), losers[0]

    check = sessions()
    account = credits.get_account(check, user.id)
    assert account.available_balance == 20
    assert account.reserved_balance == 80
    reserves = check.scalar(
        select(func.count())
        .select_from(CreditLedgerEntry)
        .where(
            CreditLedgerEntry.account_id == account.id,
            CreditLedgerEntry.type == LedgerEntryType.RESERVE,
        )
    )
    assert reserves == 1


def test_capture_and_release_cannot_both_settle_one_reservation(
    sessions: SessionFactory,
) -> None:
    """A worker finishing while a cancellation lands: one settlement, not two.

    This is the "a reserve ends in exactly one capture or release" invariant.
    Both succeeding would hand the credits back and bill them.
    """
    setup = sessions()
    user = _seed_account(setup, balance=200)
    job = make_job(setup, user, reserved=50)
    credits.reserve(setup, user.id, 50, job_id=job.id)
    setup.commit()

    def capture(session: Session) -> str:
        credits.capture(session, user.id, job_id=job.id, actual_amount=50)
        return "capture"

    def release(session: Session) -> str:
        credits.release(session, user.id, job_id=job.id, reason="cancelled")
        return "release"

    outcomes = run_in_parallel([race(capture, sessions), race(release, sessions)])
    winners = [o for o in outcomes if not isinstance(o, BaseException)]
    assert len(winners) == 1, f"expected exactly one settlement, got {outcomes}"

    check = sessions()
    account = credits.get_account(check, user.id)
    assert account.reserved_balance == 0
    settlements = check.scalars(
        select(CreditLedgerEntry.type).where(
            CreditLedgerEntry.job_id == job.id,
            CreditLedgerEntry.type.in_(
                [LedgerEntryType.CAPTURE.value, LedgerEntryType.RELEASE.value]
            ),
        )
    ).all()
    assert len(settlements) == 1
    # The balance follows whichever settlement won, with nothing left reserved.
    expected = 150 if settlements[0] == LedgerEntryType.CAPTURE else 200
    assert account.available_balance == expected


def test_redelivered_payment_webhook_books_credits_once(sessions: SessionFactory) -> None:
    """Providers retry webhooks, sometimes alongside the original delivery."""
    setup = sessions()
    user = make_user(setup, email="payer@example.com", handle="payer")
    setup.commit()

    reference = "pi_race_1"

    def book(session: Session) -> int:
        return credits.purchase(
            session, user.id, 500, payment_reference=reference
        ).available_balance

    outcomes = run_in_parallel([race(book, sessions) for _ in range(3)])
    winners = [o for o in outcomes if not isinstance(o, BaseException)]
    assert len(winners) == 1, f"payment booked {len(winners)} times: {outcomes}"

    check = sessions()
    account = credits.get_account(check, user.id)
    assert account.available_balance == 500
    booked = check.scalar(
        select(func.count())
        .select_from(CreditLedgerEntry)
        .where(CreditLedgerEntry.payment_reference == reference)
    )
    assert booked == 1


def test_parallel_grants_never_lose_a_write(sessions: SessionFactory) -> None:
    """Optimistic locking must not drop a write it reported as applied.

    Every grant here carries a distinct idempotency key, so each is legitimate:
    whichever ones report success must all be visible in the final balance.
    """
    setup = sessions()
    user = make_user(setup, email="granter@example.com", handle="granter")
    credits.get_or_create_account(setup, user.id)
    setup.commit()

    def grant(index: int) -> Callable[[Session], int]:
        def work(session: Session) -> int:
            return credits.grant(
                session, user.id, 10, idempotency_key=f"race-grant-{index}"
            ).available_balance

        return work

    outcomes = run_in_parallel([race(grant(index), sessions) for index in range(6)])
    succeeded = [o for o in outcomes if not isinstance(o, BaseException)]
    assert succeeded, f"every grant lost the race: {outcomes}"
    for failure in (o for o in outcomes if isinstance(o, BaseException)):
        assert _is_expected_loss(failure), failure

    check = sessions()
    account = check.scalar(select(CreditAccount).where(CreditAccount.user_id == user.id))
    assert account is not None
    booked = check.scalar(
        select(func.count())
        .select_from(CreditLedgerEntry)
        .where(
            CreditLedgerEntry.account_id == account.id,
            CreditLedgerEntry.type == LedgerEntryType.GRANT,
        )
    )
    # No lost updates: the balance, the ledger and the version counter all agree
    # on exactly how many grants landed.
    assert account.available_balance == 10 * len(succeeded)
    assert booked == len(succeeded)
    assert account.version == len(succeeded)
