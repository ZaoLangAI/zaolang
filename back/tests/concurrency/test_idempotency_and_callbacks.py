"""Races on the idempotency table and the job state machine.

Two failure modes matter here. A client that retries a submission before the
first one answers must not get two jobs; and provider callbacks that arrive out
of order — or after the job is already finished — must not reopen a terminal job
or punch holes in the event stream that SSE resumption depends on.
"""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.api import idempotency
from app.domain.credits import service as credits
from app.domain.errors import IdempotencyConflict, InvalidJobTransition
from app.domain.jobs import state_machine
from app.models import GenerationJob, IdempotencyRecord, JobEvent
from app.models.enums import JobEventType, JobStatus
from tests.concurrency.conftest import race, run_in_parallel
from tests.conftest import make_user
from tests.factories import make_job

SessionFactory = Callable[[], Session]

ENDPOINT = "POST /v1/generation-jobs"


def test_same_key_submitted_twice_records_one_outcome(sessions: SessionFactory) -> None:
    """A double-clicked submit must leave exactly one stored outcome.

    Both requests miss the replay lookup because neither has committed yet, so
    the unique constraint is the only thing standing between the user and two
    jobs. Exactly one `remember` may survive.
    """
    setup = sessions()
    user = make_user(setup, email="idem@example.com", handle="idem")
    setup.commit()

    body = {"operation": "text_to_image", "prompt": "两次点击"}
    request_hash = idempotency.hash_request(body)

    def submit(session: Session) -> str:
        replay = idempotency.find_replay(
            session, user_id=user.id, endpoint=ENDPOINT, key="key-1", request_hash=request_hash
        )
        if replay is not None:
            return "replayed"
        idempotency.remember(
            session,
            user_id=user.id,
            endpoint=ENDPOINT,
            key="key-1",
            request_hash=request_hash,
            status_code=201,
            response={"id": "job_x"},
        )
        return "created"

    outcomes = run_in_parallel([race(submit, sessions) for _ in range(4)])
    created = [o for o in outcomes if o == "created"]
    assert len(created) == 1, f"expected one creation, got {outcomes}"
    for failure in (o for o in outcomes if isinstance(o, BaseException)):
        assert isinstance(failure, IdempotencyConflict | SQLAlchemyError | IntegrityError), failure

    check = sessions()
    stored = check.scalar(
        select(func.count())
        .select_from(IdempotencyRecord)
        .where(
            IdempotencyRecord.user_id == user.id,
            IdempotencyRecord.idempotency_key == "key-1",
        )
    )
    assert stored == 1


def test_same_key_with_a_changed_body_is_a_conflict(sessions: SessionFactory) -> None:
    """Reusing a key for a different request is a client bug, not a retry."""
    setup = sessions()
    user = make_user(setup, email="idem2@example.com", handle="idem2")
    first = idempotency.hash_request({"prompt": "一"})
    idempotency.remember(
        setup,
        user_id=user.id,
        endpoint=ENDPOINT,
        key="key-2",
        request_hash=first,
        status_code=201,
        response={"id": "job_a"},
    )
    setup.commit()

    check = sessions()
    replay = idempotency.find_replay(
        check, user_id=user.id, endpoint=ENDPOINT, key="key-2", request_hash=first
    )
    assert replay is not None
    assert replay.response_snapshot == {"id": "job_a"}

    try:
        idempotency.find_replay(
            check,
            user_id=user.id,
            endpoint=ENDPOINT,
            key="key-2",
            request_hash=idempotency.hash_request({"prompt": "二"}),
        )
    except IdempotencyConflict:
        pass
    else:  # pragma: no cover - the assertion below reports the failure
        raise AssertionError("a changed body reusing the key should conflict")


def test_only_one_terminal_transition_wins(sessions: SessionFactory) -> None:
    """Success and failure callbacks arriving together settle the job once.

    Both providers think they own the job. Whichever transition lands first
    fixes the outcome; the other must be refused rather than overwriting it.
    """
    setup = sessions()
    user = make_user(setup, email="jobs@example.com", handle="jobsracer")
    job = make_job(setup, user, status=JobStatus.RUNNING)
    setup.commit()

    def succeed(session: Session) -> str:
        state_machine.transition(
            session, job.id, JobStatus.SUCCEEDED, actual_credits=job.reserved_credits
        )
        return "succeeded"

    def fail(session: Session) -> str:
        state_machine.transition(session, job.id, JobStatus.FAILED, failure_code="PROVIDER_ERROR")
        return "failed"

    outcomes = run_in_parallel([race(succeed, sessions), race(fail, sessions)])
    winners = [o for o in outcomes if not isinstance(o, BaseException)]
    assert len(winners) == 1, f"expected one terminal transition, got {outcomes}"
    for failure in (o for o in outcomes if isinstance(o, BaseException)):
        assert isinstance(failure, InvalidJobTransition | SQLAlchemyError), failure

    check = sessions()
    settled = check.get(GenerationJob, job.id)
    assert settled is not None
    assert settled.status == winners[0]
    assert settled.finished_at is not None


def test_a_late_callback_cannot_reopen_a_finished_job(sessions: SessionFactory) -> None:
    """Out-of-order delivery: `running` arrives after the job already finished."""
    setup = sessions()
    user = make_user(setup, email="late@example.com", handle="latecallback")
    job = make_job(setup, user, status=JobStatus.RUNNING)
    state_machine.transition(setup, job.id, JobStatus.SUCCEEDED, actual_credits=12)
    setup.commit()

    check = sessions()
    for stale_target in (JobStatus.RUNNING, JobStatus.SUBMITTED, JobStatus.FAILED):
        try:
            state_machine.transition(check, job.id, stale_target)
        except InvalidJobTransition:
            check.rollback()
            continue
        raise AssertionError(f"a terminal job accepted a move to {stale_target}")

    settled = check.get(GenerationJob, job.id)
    assert settled is not None
    assert settled.status == JobStatus.SUCCEEDED


def test_parallel_event_writers_keep_the_stream_usable(sessions: SessionFactory) -> None:
    """Concurrent writers must not produce duplicate or missing sequences.

    SSE resumption reads `sequence > last_event_id`, so a duplicate would be
    skipped and a hole would strand the client. A writer that loses the unique
    constraint is fine; a corrupted stream is not.
    """
    setup = sessions()
    user = make_user(setup, email="events@example.com", handle="eventsracer")
    job = make_job(setup, user, status=JobStatus.RUNNING)
    setup.commit()

    def append(index: int) -> Callable[[Session], int]:
        def work(session: Session) -> int:
            event = state_machine.append_event(
                session,
                job.id,
                event_type=JobEventType.PROGRESS,
                status=JobStatus.RUNNING,
                public_message=f"进度 {index}",
                progress=10 * index,
            )
            return event.sequence

        return work

    writers = 5
    outcomes = run_in_parallel([race(append(index), sessions) for index in range(writers)])
    landed = [o for o in outcomes if not isinstance(o, BaseException)]
    assert landed, f"every event writer lost: {outcomes}"

    check = sessions()
    sequences = [
        event.sequence
        for event in check.scalars(
            select(JobEvent).where(JobEvent.job_id == job.id).order_by(JobEvent.sequence)
        )
    ]
    assert len(sequences) == len(set(sequences)), f"duplicate sequences: {sequences}"
    assert sequences == list(range(1, len(sequences) + 1)), f"gap in stream: {sequences}"
    # Everything written is reachable from a cold resume.
    assert len(state_machine.events_since(check, job.id, 0)) == len(sequences)


def test_release_after_a_forced_termination_happens_once(sessions: SessionFactory) -> None:
    """An operator killing a job while the worker fails it: one refund.

    Both paths want to hand the reservation back, and both are legitimate
    requests — but the user must not be refunded twice.
    """
    setup = sessions()
    user = make_user(setup, email="killer@example.com", handle="killer")
    credits.grant(setup, user.id, 100, idempotency_key=f"seed:{user.id}")
    job = make_job(setup, user, status=JobStatus.RUNNING, reserved=40)
    credits.reserve(setup, user.id, 40, job_id=job.id)
    setup.commit()

    def refund(reason: str) -> Callable[[Session], str]:
        def work(session: Session) -> str:
            credits.release(session, user.id, job_id=job.id, reason=reason)
            return reason

        return work

    outcomes = run_in_parallel(
        [race(refund("operator_terminated"), sessions), race(refund("worker_failed"), sessions)]
    )
    winners = [o for o in outcomes if not isinstance(o, BaseException)]
    assert len(winners) == 1, f"refunded {len(winners)} times: {outcomes}"

    check = sessions()
    account = credits.get_account(check, user.id)
    assert account.available_balance == 100
    assert account.reserved_balance == 0
