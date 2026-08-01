"""Generation job state machine."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.domain.errors import InvalidJobTransition, JobNotCancellable
from app.domain.jobs import state_machine as sm
from app.models import User
from app.models.enums import (
    JOB_TRANSITIONS,
    JobEventType,
    JobStatus,
    can_transition,
)
from tests.factories import make_job


def test_happy_path_transitions_are_allowed(db: Session, author: User) -> None:
    job = make_job(db, author)

    for target in (JobStatus.QUEUED, JobStatus.SUBMITTED, JobStatus.RUNNING, JobStatus.SUCCEEDED):
        job = sm.transition(db, job.id, target)

    assert job.status == JobStatus.SUCCEEDED
    assert job.finished_at is not None


def test_terminal_states_have_no_outgoing_transitions() -> None:
    for status in (JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED, JobStatus.EXPIRED):
        assert JOB_TRANSITIONS[status] == frozenset()


def test_succeeded_job_cannot_go_back_to_running(db: Session, author: User) -> None:
    """A late provider callback must not reopen a settled job."""
    job = make_job(db, author, status=JobStatus.SUCCEEDED)

    with pytest.raises(InvalidJobTransition):
        sm.transition(db, job.id, JobStatus.RUNNING)


def test_failed_job_cannot_be_marked_succeeded(db: Session, author: User) -> None:
    job = make_job(db, author, status=JobStatus.FAILED)

    with pytest.raises(InvalidJobTransition):
        sm.transition(db, job.id, JobStatus.SUCCEEDED)


def test_created_job_cannot_jump_straight_to_running(db: Session, author: User) -> None:
    job = make_job(db, author, status=JobStatus.CREATED)

    with pytest.raises(InvalidJobTransition):
        sm.transition(db, job.id, JobStatus.RUNNING)


def test_transition_table_matches_the_helper() -> None:
    assert can_transition(JobStatus.QUEUED, JobStatus.SUBMITTED) is True
    assert can_transition(JobStatus.QUEUED, JobStatus.SUCCEEDED) is False


def test_failure_details_are_recorded(db: Session, author: User) -> None:
    job = make_job(db, author, status=JobStatus.RUNNING)

    job = sm.transition(
        db,
        job.id,
        JobStatus.FAILED,
        failure_code="PROVIDER_TEMPORARY_FAILURE",
        failure_message="上游超时",
    )

    assert job.failure_code == "PROVIDER_TEMPORARY_FAILURE"


def test_cancel_is_a_request_not_an_immediate_terminal_state(db: Session, author: User) -> None:
    """A submitted job may still finish at the provider and bill us."""
    job = make_job(db, author, status=JobStatus.SUBMITTED)

    job = sm.request_cancel(db, job.id)

    assert job.cancel_requested_at is not None
    assert job.status == JobStatus.SUBMITTED


def test_cancel_is_idempotent(db: Session, author: User) -> None:
    job = make_job(db, author, status=JobStatus.RUNNING)

    first = sm.request_cancel(db, job.id)
    second = sm.request_cancel(db, job.id)

    assert first.cancel_requested_at == second.cancel_requested_at


def test_terminal_job_cannot_be_cancelled(db: Session, author: User) -> None:
    job = make_job(db, author, status=JobStatus.SUCCEEDED)

    with pytest.raises(JobNotCancellable):
        sm.request_cancel(db, job.id)


def test_events_are_appended_with_a_gapless_sequence(db: Session, author: User) -> None:
    job = make_job(db, author)

    for index in range(5):
        sm.append_event(
            db,
            job.id,
            event_type=JobEventType.PROGRESS,
            status=JobStatus.RUNNING,
            public_message=f"进度 {index}",
            progress=index * 20,
        )

    events = sm.events_since(db, job.id, 0)
    assert [e.sequence for e in events] == [1, 2, 3, 4, 5]


def test_events_can_be_replayed_from_a_last_event_id(db: Session, author: User) -> None:
    job = make_job(db, author)
    for index in range(4):
        sm.append_event(
            db,
            job.id,
            event_type=JobEventType.PROGRESS,
            status=JobStatus.RUNNING,
            public_message=f"进度 {index}",
        )

    resumed = sm.events_since(db, job.id, after_sequence=2)

    assert [e.sequence for e in resumed] == [3, 4]


def test_progress_is_clamped_to_a_percentage(db: Session, author: User) -> None:
    job = make_job(db, author)

    event = sm.append_event(
        db,
        job.id,
        event_type=JobEventType.PROGRESS,
        status=JobStatus.RUNNING,
        public_message="超范围",
        progress=140,
    )

    assert event.progress == 100
