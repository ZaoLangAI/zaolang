"""Races against the monthly spend cap: it is enforced inside the same
conditional UPDATE as the balance, so two reserves that each fit alone but
not together can never both win."""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy.exc import DBAPIError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.domain.credits import service as credits
from app.domain.errors import Conflict, SpendLimitExceeded
from tests.concurrency.conftest import race, run_in_parallel
from tests.conftest import make_user
from tests.factories import make_job

SessionFactory = Callable[[], Session]


def test_two_reserves_cannot_both_fit_under_the_cap(sessions: SessionFactory) -> None:
    setup = sessions()
    user = make_user(setup, email="capped@example.com", handle="capped")
    credits.grant(setup, user.id, 1_000, idempotency_key=f"seed:{user.id}")
    credits.set_monthly_spend_limit(setup, user.id, 100)
    job_a = make_job(setup, user, reserved=80)
    job_b = make_job(setup, user, reserved=80)
    setup.commit()

    def reserve(job_id: str) -> Callable[[Session], int]:
        def work(session: Session) -> int:
            credits.get_account(session, user.id)
            return credits.reserve(session, user.id, 80, job_id=job_id).reserved_balance

        return work

    outcomes = run_in_parallel(
        [race(reserve(job_a.id), sessions), race(reserve(job_b.id), sessions)]
    )

    winners = [outcome for outcome in outcomes if not isinstance(outcome, BaseException)]
    losers = [outcome for outcome in outcomes if isinstance(outcome, BaseException)]
    assert len(winners) == 1, f"expected exactly one winner, got {outcomes}"
    assert isinstance(losers[0], Conflict | SpendLimitExceeded | SQLAlchemyError | DBAPIError), (
        losers[0]
    )
    account = credits.get_account(sessions(), user.id)
    assert account.period_spent == 80
    assert account.available_balance == 920
