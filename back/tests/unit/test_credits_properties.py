"""Property-based checks on the ledger and the job state machine.

The example-based tests in `test_credits_invariants.py` pin down the cases we
thought of; these generate the ones we did not. Arbitrary sequences of ledger
operations and arbitrary walks through the status graph are applied, and the
assertions are the invariants themselves, so any sequence that breaks one comes
back as a shrunk counterexample instead of passing unnoticed.
"""

from __future__ import annotations

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.credits import service as credits
from app.domain.errors import Conflict, InsufficientCredits, InvalidJobTransition
from app.domain.jobs import state_machine
from app.models import CreditLedgerEntry, GenerationJob, User
from app.models.base import new_id
from app.models.enums import JOB_TRANSITIONS, JobEventType, JobStatus, LedgerEntryType
from tests.conftest import make_user
from tests.factories import make_job

# Hypothesis reuses a function-scoped fixture across examples, which it warns
# about by default. Rebuilding a Postgres schema per example would make these
# tests unusably slow, so the check is suppressed and each example isolates
# itself instead — either with a SAVEPOINT or by using unique keys.
PROPERTY_SETTINGS = settings(
    max_examples=50,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)

LEDGER_OPERATIONS = st.sampled_from(["reserve", "capture", "release", "grant"])


@PROPERTY_SETTINGS
@given(
    grant_amount=st.integers(min_value=1, max_value=10_000),
    operations=st.lists(
        st.tuples(LEDGER_OPERATIONS, st.integers(min_value=1, max_value=2_000)),
        min_size=1,
        max_size=10,
    ),
)
def test_ledger_never_violates_its_invariants(
    committed_db: Session, grant_amount: int, operations: list[tuple[str, int]]
) -> None:
    """Balances stay non-negative and reconcile with the ledger, always.

    Illegal steps in the sequence are expected — a second reserve on the same
    job, a capture after a release — and each is required to leave the balances
    untouched. What must hold at the end is that the account is non-negative
    and equal to the replayed ledger.

    A fresh user per example keeps the ledger's unique keys from colliding
    across examples, which would otherwise report a fixture problem as a
    property violation.
    """
    user = make_user(committed_db, email=f"prop-{new_id('u')}@example.com")
    credits.grant(committed_db, user.id, grant_amount, idempotency_key=f"grant:{user.id}")
    job = make_job(committed_db, user)
    committed_db.commit()

    grant_counter = 0
    for name, amount in operations:
        try:
            if name == "reserve":
                credits.reserve(committed_db, user.id, amount, job_id=job.id)
            elif name == "capture":
                credits.capture(committed_db, user.id, job_id=job.id, actual_amount=amount)
            elif name == "release":
                credits.release(committed_db, user.id, job_id=job.id)
            else:
                grant_counter += 1
                credits.grant(
                    committed_db,
                    user.id,
                    amount,
                    idempotency_key=f"grant:{user.id}:{grant_counter}",
                )
            committed_db.commit()
        except (Conflict, InsufficientCredits):
            # A refusal is a valid outcome. It must not have moved anything,
            # which the end-state assertions below verify for the whole run.
            committed_db.rollback()

    account = credits.get_account(committed_db, user.id)
    assert account.available_balance >= 0
    assert account.reserved_balance >= 0

    entries = list(
        committed_db.scalars(
            select(CreditLedgerEntry)
            .where(CreditLedgerEntry.account_id == account.id)
            .order_by(CreditLedgerEntry.created_at, CreditLedgerEntry.id)
        )
    )
    # The account is a cache of the ledger. Reserve and release only shuffle
    # credits between the two buckets, so the identity that must hold is:
    # money in, minus money actually captured, equals everything still held.
    inflow = sum(entry.amount for entry in entries if entry.type == LedgerEntryType.GRANT)
    captured = -sum(entry.amount for entry in entries if entry.type == LedgerEntryType.CAPTURE)
    assert inflow - captured == account.available_balance + account.reserved_balance
    assert entries[-1].balance_after == account.available_balance
    assert entries[-1].reserved_after == account.reserved_balance

    settlements = [
        entry.type
        for entry in entries
        if entry.job_id == job.id
        and entry.type in (LedgerEntryType.CAPTURE, LedgerEntryType.RELEASE)
    ]
    # A reservation settles at most once, and never both ways.
    assert len(settlements) <= 1


@PROPERTY_SETTINGS
@given(
    reserved=st.integers(min_value=1, max_value=5_000),
    actual=st.integers(min_value=0, max_value=20_000),
)
def test_capture_never_bills_above_the_reservation(
    db: Session, author: User, reserved: int, actual: int
) -> None:
    """However much the provider claims, the user pays at most the quote.

    The overspend case is the point: a provider reporting more than we reserved
    must be clamped rather than allowed to overdraw the account.
    """
    savepoint = db.begin_nested()
    try:
        credits.grant(db, author.id, reserved, idempotency_key=f"cap:{new_id('k')}")
        job = make_job(db, author, reserved=reserved)
        credits.reserve(db, author.id, reserved, job_id=job.id)

        result = credits.capture(db, author.id, job_id=job.id, actual_amount=actual)

        settled = min(actual, reserved)
        assert result.entry.amount == -settled
        assert result.reserved_balance == 0
        # Whatever was not consumed comes straight back to available.
        assert result.available_balance == reserved - settled
    finally:
        savepoint.rollback()


@PROPERTY_SETTINGS
@given(
    suffix=st.text(
        # Control characters are excluded because an idempotency key arrives in
        # an HTTP header, which cannot carry them, and Postgres text columns
        # reject NUL outright. Everything else — CJK, emoji, punctuation — is
        # fair game and must round-trip.
        alphabet=st.characters(blacklist_categories=("Cc", "Cs")),
        min_size=1,
        max_size=40,
    ).filter(lambda s: s.strip() != "")
)
def test_repeating_a_grant_key_is_rejected(committed_db: Session, suffix: str) -> None:
    """Idempotency holds for any key, not just tidy ASCII ones.

    The uniqueness constraint is global rather than per-account, so the
    generated text is prefixed with a nonce; without it, two examples drawing
    the same string would collide with each other instead of testing anything.
    """
    key = f"{new_id('k')}:{suffix}"
    user = make_user(committed_db, email=f"idem-{new_id('u')}@example.com")
    credits.grant(committed_db, user.id, 50, idempotency_key=key)
    committed_db.commit()

    with pytest.raises(Conflict):
        credits.grant(committed_db, user.id, 50, idempotency_key=key)
    committed_db.rollback()

    assert credits.get_account(committed_db, user.id).available_balance == 50
    booked = committed_db.scalar(
        select(func.count())
        .select_from(CreditLedgerEntry)
        .where(CreditLedgerEntry.idempotency_key == key)
    )
    assert booked == 1


@PROPERTY_SETTINGS
@given(targets=st.lists(st.sampled_from(list(JobStatus)), min_size=1, max_size=8))
def test_job_status_walk_respects_the_transition_table(
    db: Session, author: User, targets: list[JobStatus]
) -> None:
    """Any walk through the status graph either follows the table or is refused.

    A terminal job in particular must stay terminal: no ordering of late
    provider callbacks may reopen it.
    """
    savepoint = db.begin_nested()
    try:
        job = make_job(db, author)
        current = JobStatus(job.status)

        for target in targets:
            legal = target in JOB_TRANSITIONS.get(current, set())
            try:
                state_machine.transition(db, job.id, target)
            except InvalidJobTransition:
                assert not legal, f"{current} → {target} should have been allowed"
                continue
            assert legal, f"{current} → {target} should have been refused"
            current = target

        db.expire_all()
        refreshed = db.get(GenerationJob, job.id)
        assert refreshed is not None
        assert refreshed.status == current.value
        if current.is_terminal:
            assert refreshed.finished_at is not None
    finally:
        savepoint.rollback()


@PROPERTY_SETTINGS
@given(batches=st.lists(st.integers(min_value=1, max_value=5), min_size=1, max_size=4))
def test_event_sequences_stay_gapless(db: Session, author: User, batches: list[int]) -> None:
    """SSE resumption depends on `sequence` having no holes and no repeats."""
    savepoint = db.begin_nested()
    try:
        job = make_job(db, author)
        total = 0
        for batch in batches:
            for _ in range(batch):
                total += 1
                state_machine.append_event(
                    db,
                    job.id,
                    event_type=JobEventType.PROGRESS,
                    status=JobStatus.RUNNING,
                    public_message="进行中",
                    progress=min(99, total),
                )

        assert [e.sequence for e in state_machine.events_since(db, job.id, 0)] == list(
            range(1, total + 1)
        )
        # Resuming from any point returns exactly the unseen tail.
        for cut in range(total + 1):
            tail = state_machine.events_since(db, job.id, cut)
            assert [e.sequence for e in tail] == list(range(cut + 1, total + 1))
    finally:
        savepoint.rollback()
