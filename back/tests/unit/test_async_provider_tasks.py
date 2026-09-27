"""Suspend-and-resume around an external render.

The AiHubMix video protocol hands work to an upstream that takes minutes. The
worker submits, parks the job on an `AsyncProviderTask` and lets go; a beat
tick picks it back up. What these tests protect is the part a user notices —
the job keeps reporting progress and always reaches a terminal state — and the
part an operator notices — nothing is settled twice.
"""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents import router
from app.domain.credits import service as credits_service
from app.domain.jobs import async_tasks
from app.domain.jobs import service as jobs_service
from app.domain.jobs import state_machine as sm
from app.models import (
    AsyncProviderTask,
    CreditLedgerEntry,
    JobEvent,
    Notification,
    ProviderAttempt,
    User,
)
from app.models.base import new_id, utcnow
from app.models.enums import (
    JobStatus,
    LedgerEntryType,
    NotificationType,
    Operation,
    ProviderAttemptStatus,
    ProviderKind,
    QualityTier,
)
from app.providers.base import GenerationRequest, GenerationResult, ProviderCapability
from app.storage.s3 import put_object
from app.workers import async_polling, pipeline

CAPABILITY_NAME = "async_video"


class _AsyncProvider:
    """An upstream that accepts the work and settles only when told to.

    `outcomes` is consumed one poll at a time, so a test spells out the exact
    sequence a tick will see rather than depending on wall-clock timing.
    """

    name = CAPABILITY_NAME
    kind = ProviderKind.COMMERCIAL_API

    def __init__(self) -> None:
        self.outcomes: list[GenerationResult] = []
        self.cancelled: list[str] = []
        self.polls: list[str] = []

    def submit(self, request: GenerationRequest) -> GenerationResult:
        return GenerationResult(succeeded=False, pending=True, external_task_id="ext_1")

    def poll(self, external_task_id: str, request: GenerationRequest) -> GenerationResult:
        self.polls.append(external_task_id)
        if not self.outcomes:
            return GenerationResult(
                succeeded=False, pending=True, external_task_id=external_task_id
            )
        outcome = self.outcomes.pop(0)
        if outcome.succeeded and outcome.object_key:
            # The real provider downloads the finished render before
            # returning; the resumed workflow reads the object straight away.
            put_object(outcome.object_key, b"video-bytes", content_type=outcome.mime_type)
        return outcome

    def cancel(self, external_task_id: str) -> bool:
        self.cancelled.append(external_task_id)
        return True


@pytest.fixture
def provider(monkeypatch: pytest.MonkeyPatch, db: Session) -> _AsyncProvider:
    """Makes the async provider the only route any job can take."""
    instance = _AsyncProvider()
    from tests.llm_catalog import bind_default_agents_to_catalog

    bind_default_agents_to_catalog(db)
    monkeypatch.setattr(
        router,
        "build_catalog",
        lambda session: {
            CAPABILITY_NAME: ProviderCapability(
                name=CAPABILITY_NAME,
                kind=ProviderKind.COMMERCIAL_API,
                operations=frozenset({Operation.TEXT_TO_VIDEO, Operation.IMAGE_TO_VIDEO}),
                tiers=frozenset({QualityTier.PREVIEW, QualityTier.STANDARD}),
                quality_prior=0.9,
                typical_latency_ms=60_000,
                unit_cost_micro_usd=200000,
                model_or_workflow="minimax-h3",
                provider_factory=lambda: instance,
            )
        },
    )
    return instance


@pytest.fixture
def funded(db: Session, author: User) -> User:
    credits_service.grant(db, author.id, 50_000, idempotency_key=new_id("grant"))
    db.flush()
    return author


def _submit_video(db: Session, user: User):
    return jobs_service.submit(
        db,
        user_id=user.id,
        operation=Operation.TEXT_TO_VIDEO,
        quality_tier=QualityTier.STANDARD,
        params={"prompt": "霓虹街头的猫", "aspect_ratio": "16:9", "duration_seconds": 5},
        idempotency_key=new_id("idk"),
    ).job


def _suspended(db: Session, user: User):
    """Runs a video job up to the point the upstream takes over."""
    job = _submit_video(db, user)
    outcome = pipeline.run_generation_pipeline(db, job.id)
    assert outcome.status == JobStatus.RUNNING
    db.refresh(job)
    return job


def _finished(**overrides) -> GenerationResult:
    defaults = {
        "succeeded": True,
        "object_key": "generated/video.mp4",
        "mime_type": "video/mp4",
        "width": 1920,
        "height": 1080,
        "duration_ms": 5_000,
        "cost_minor": 20,
        "latency_ms": 61_000,
    }
    return GenerationResult(**{**defaults, **overrides})


def _due(db: Session, job_id: str) -> AsyncProviderTask:
    """Brings the task's next check forward so a tick will pick it up."""
    task = async_tasks.find_for_job(db, job_id)
    assert task is not None
    task.next_poll_at = utcnow() - dt.timedelta(seconds=1)
    db.flush()
    return task


def test_a_pending_render_parks_the_job_instead_of_finishing_it(
    db: Session, funded: User, provider: _AsyncProvider
) -> None:
    """`RUNNING` with a task row is the one state where nobody is executing
    the job and that is still correct — the credits stay reserved because the
    work is genuinely in flight."""
    job = _suspended(db, funded)

    assert job.status == JobStatus.RUNNING
    task = async_tasks.find_for_job(db, job.id)
    assert task is not None
    assert task.external_task_id == "ext_1"
    assert task.capability_name == CAPABILITY_NAME

    account = credits_service.get_or_create_account(db, funded.id)
    assert account.reserved_balance == job.reserved_credits

    attempt = db.scalar(select(ProviderAttempt).where(ProviderAttempt.job_id == job.id))
    assert attempt is not None and attempt.status == ProviderAttemptStatus.RUNNING


def test_a_render_still_running_produces_a_heartbeat_and_books_the_next_check(
    db: Session, funded: User, provider: _AsyncProvider
) -> None:
    """Without this the user watches one frozen status for minutes, which
    looks exactly like a job that died."""
    job = _suspended(db, funded)
    before = len(sm.events_since(db, job.id, 0))
    _due(db, job.id)

    assert async_polling.poll_once(db) == 1

    events = sm.events_since(db, job.id, 0)
    assert len(events) > before
    task = async_tasks.find_for_job(db, job.id)
    assert task is not None
    assert task.poll_count == 1
    assert task.claimed_at is None
    assert task.next_poll_at > utcnow()
    assert task.deadline_at > utcnow()

    db.refresh(job)
    assert job.status == JobStatus.RUNNING


def test_heartbeat_progress_never_goes_backwards(
    db: Session, funded: User, provider: _AsyncProvider
) -> None:
    job = _suspended(db, funded)
    for _ in range(3):
        _due(db, job.id)
        async_polling.poll_once(db)

    progress = [
        event.progress
        for event in db.scalars(
            select(JobEvent).where(JobEvent.job_id == job.id).order_by(JobEvent.sequence)
        )
    ]
    assert progress == sorted(progress)


def test_heartbeat_maps_upstream_progress_into_its_reserved_window(
    db: Session, funded: User, provider: _AsyncProvider
) -> None:
    """OpenAI's video status response sometimes carries its own `0`-`100`
    `progress` field; it must land inside the 46-70 heartbeat window rather
    than leaking through raw, and must never regress the poll-count floor."""
    job = _suspended(db, funded)
    _due(db, job.id)
    provider.outcomes = []

    def _pending_with_progress(*_args, **_kwargs):
        return GenerationResult(
            succeeded=False, pending=True, external_task_id="ext_1", metadata={"progress": 50}
        )

    import types

    provider.poll = types.MethodType(  # type: ignore[method-assign]
        lambda self, external_task_id, request: _pending_with_progress(), provider
    )

    async_polling.poll_once(db)

    event = db.scalar(
        select(JobEvent).where(JobEvent.job_id == job.id).order_by(JobEvent.sequence.desc())
    )
    assert event is not None
    assert async_polling._PROGRESS_FLOOR < event.progress < async_polling._PROGRESS_CEILING

    # A later poll reporting a lower upstream number must not move the bar
    # backwards from what poll_count already earned.
    _due(db, job.id)
    provider.poll = types.MethodType(
        lambda self, external_task_id, request: GenerationResult(
            succeeded=False, pending=True, external_task_id="ext_1", metadata={"progress": 1}
        ),
        provider,
    )
    previous_progress = event.progress
    async_polling.poll_once(db)
    latest = db.scalar(
        select(JobEvent).where(JobEvent.job_id == job.id).order_by(JobEvent.sequence.desc())
    )
    assert latest is not None
    assert latest.progress >= previous_progress


def test_a_resume_crash_after_quality_check_keeps_the_checkpoint(
    db: Session, funded: User, provider: _AsyncProvider, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Settling the row before `resume()` used to orphan the job: the user
    saw quality_check, the render was already on disk, and nobody came back."""
    from sqlalchemy.exc import IntegrityError

    job = _suspended(db, funded)
    provider.outcomes = [_finished()]
    _due(db, job.id)

    original = async_polling.WorkflowRunner.resume
    calls = {"n": 0}

    def _boom(self, ctx, *, node_id, port):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        if calls["n"] == 1:
            raise IntegrityError("notify", {}, Exception("duplicate key"))
        return original(self, ctx, node_id=node_id, port=port)

    monkeypatch.setattr(async_polling.WorkflowRunner, "resume", _boom)

    assert async_polling.poll_once(db) == 0
    db.refresh(job)
    assert job.status == JobStatus.RUNNING
    task = async_tasks.find_for_job(db, job.id)
    assert task is not None
    assert (task.state_checkpoint_json or {}).get("parked_resume", {}).get("kind") == "succeeded"
    assert task.claimed_at is None
    account = credits_service.get_or_create_account(db, funded.id)
    assert account.reserved_balance == job.reserved_credits

    _due(db, job.id)
    assert async_polling.poll_once(db) == 1
    db.refresh(job)
    assert job.status == JobStatus.SUCCEEDED
    assert async_tasks.find_for_job(db, job.id) is None
    assert account.reserved_balance == 0
    captures = list(
        db.scalars(
            select(CreditLedgerEntry).where(CreditLedgerEntry.type == LedgerEntryType.CAPTURE)
        )
    )
    assert len(captures) == 1


def test_a_completed_render_resumes_the_workflow_through_to_settlement(
    db: Session, funded: User, provider: _AsyncProvider
) -> None:
    job = _suspended(db, funded)
    provider.outcomes = [_finished()]
    _due(db, job.id)

    async_polling.poll_once(db)

    db.refresh(job)
    assert job.status == JobStatus.SUCCEEDED
    assert async_tasks.find_for_job(db, job.id) is None

    account = credits_service.get_or_create_account(db, funded.id)
    assert account.reserved_balance == 0
    captures = list(
        db.scalars(
            select(CreditLedgerEntry).where(CreditLedgerEntry.type == LedgerEntryType.CAPTURE)
        )
    )
    assert len(captures) == 1

    attempt = db.scalar(select(ProviderAttempt).where(ProviderAttempt.job_id == job.id))
    assert attempt is not None and attempt.status == ProviderAttemptStatus.SUCCEEDED


def test_an_async_video_success_upserts_the_same_notification_row_to_its_terminal_state(
    db: Session, funded: User, provider: _AsyncProvider
) -> None:
    """The async render track goes through the same `sm.transition` calls a
    synchronous job does, so it must land on the one notification row the
    `queued` transition already created — not a second row, and not silence."""
    job = _suspended(db, funded)
    notes_while_running = list(
        db.scalars(select(Notification).where(Notification.target_id == job.id))
    )
    assert len(notes_while_running) == 1
    note_id = notes_while_running[0].id

    provider.outcomes = [_finished()]
    _due(db, job.id)
    async_polling.poll_once(db)

    db.refresh(job)
    assert job.status == JobStatus.SUCCEEDED
    notes = list(db.scalars(select(Notification).where(Notification.target_id == job.id)))
    assert len(notes) == 1
    assert notes[0].id == note_id
    assert notes[0].type == NotificationType.JOB_SUCCEEDED
    assert notes[0].payload_json["status"] == JobStatus.SUCCEEDED


def test_an_async_video_failure_upserts_the_same_notification_row_to_its_terminal_state(
    db: Session, funded: User, provider: _AsyncProvider
) -> None:
    job = _suspended(db, funded)
    note_id = db.scalar(select(Notification.id).where(Notification.target_id == job.id))
    assert note_id is not None

    provider.outcomes = [
        GenerationResult(succeeded=False, failure_code="PROVIDER_TEMPORARY_FAILURE")
    ]
    _due(db, job.id)
    async_polling.poll_once(db)
    while async_tasks.find_for_job(db, job.id) is not None:
        provider.outcomes = [
            GenerationResult(succeeded=False, failure_code="PROVIDER_TEMPORARY_FAILURE")
        ]
        _due(db, job.id)
        async_polling.poll_once(db)

    db.refresh(job)
    assert JobStatus(job.status).is_terminal
    notes = list(db.scalars(select(Notification).where(Notification.target_id == job.id)))
    assert len(notes) == 1
    assert notes[0].id == note_id
    assert notes[0].type in {NotificationType.JOB_FAILED, NotificationType.JOB_CANCELLED}
    assert notes[0].payload_json["status"] == job.status


def test_a_partial_provider_output_still_enters_quality_and_keeps_its_marker(
    db: Session, funded: User, provider: _AsyncProvider
) -> None:
    job = _suspended(db, funded)
    provider.outcomes = [_finished(metadata={"partial_output": True, "upstream_status": "failed"})]
    _due(db, job.id)

    async_polling.poll_once(db)

    db.refresh(job)
    assert job.status == JobStatus.SUCCEEDED
    attempt = db.scalar(select(ProviderAttempt).where(ProviderAttempt.job_id == job.id))
    assert attempt is not None
    assert attempt.raw_metadata_redacted_json["partial_output"] is True
    assert attempt.raw_metadata_redacted_json["upstream_status"] == "failed"


def test_a_failed_render_releases_the_reservation_rather_than_stranding_it(
    db: Session, funded: User, provider: _AsyncProvider
) -> None:
    """Every retry re-submits to the same (only) route, so the attempt budget
    is what ends this — and the job must not stay `RUNNING` after it does."""
    job = _suspended(db, funded)
    provider.outcomes = [
        GenerationResult(succeeded=False, failure_code="PROVIDER_TEMPORARY_FAILURE")
    ]
    _due(db, job.id)

    async_polling.poll_once(db)
    # The retry re-submits and suspends again; drain it the same way.
    while async_tasks.find_for_job(db, job.id) is not None:
        provider.outcomes = [
            GenerationResult(succeeded=False, failure_code="PROVIDER_TEMPORARY_FAILURE")
        ]
        _due(db, job.id)
        async_polling.poll_once(db)

    db.refresh(job)
    assert JobStatus(job.status).is_terminal
    account = credits_service.get_or_create_account(db, funded.id)
    assert account.reserved_balance == 0


def test_cancel_api_honours_a_parked_async_render_immediately(
    client, db: Session, funded: User, provider: _AsyncProvider
) -> None:
    """User cancel of a suspended video job must not wait for the next poll."""
    from tests.conftest import auth_header

    job = _suspended(db, funded)

    response = client.post(f"/v1/generation-jobs/{job.id}/cancel", headers=auth_header(funded))

    assert response.status_code == 200
    assert response.json()["status"] == JobStatus.CANCELLED
    db.refresh(job)
    assert job.status == JobStatus.CANCELLED
    assert provider.cancelled == ["ext_1"]
    assert async_tasks.find_for_job(db, job.id) is None


def test_a_cancel_during_the_render_is_honoured_on_the_next_tick(
    db: Session, funded: User, provider: _AsyncProvider
) -> None:
    """The synchronous path only checks before `submit()`, which leaves the
    whole render window unguarded."""
    job = _suspended(db, funded)
    sm.request_cancel(db, job.id)
    db.commit()
    _due(db, job.id)

    async_polling.poll_once(db)

    db.refresh(job)
    assert job.status == JobStatus.CANCELLED
    assert provider.cancelled == ["ext_1"]
    assert async_tasks.find_for_job(db, job.id) is None
    account = credits_service.get_or_create_account(db, funded.id)
    assert account.reserved_balance == 0
    # Cancelling must not have waited for the upstream to answer first.
    assert provider.polls == []


def test_cancel_upstream_notifies_closes_the_attempt_and_drops_the_task_row(
    db: Session, funded: User, provider: _AsyncProvider
) -> None:
    """The shared helper `admin/jobs.py::terminate` and `_cancel()` both call.

    Deliberately does not touch the job's own status/reservation — those
    differ per caller and are asserted by the callers' own tests
    (`test_a_cancel_during_the_render_is_honoured_on_the_next_tick` here,
    the admin termination integration test for the other caller).
    """
    job = _suspended(db, funded)
    task = async_tasks.find_for_job(db, job.id)
    assert task is not None
    attempt_id = task.provider_attempt_id

    succeeded = async_tasks.cancel_upstream(db, task, provider)

    assert succeeded is True
    assert provider.cancelled == ["ext_1"]
    assert async_tasks.find_for_job(db, job.id) is None
    attempt = db.get(ProviderAttempt, attempt_id)
    assert attempt is not None and attempt.status == ProviderAttemptStatus.CANCELLED


def test_cancel_upstream_settles_even_when_the_provider_call_raises(
    db: Session, funded: User, provider: _AsyncProvider, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A provider timing out on cancel must not strand the task row."""
    job = _suspended(db, funded)
    task = async_tasks.find_for_job(db, job.id)
    assert task is not None

    def _raise(_external_task_id: str) -> bool:
        raise TimeoutError("upstream unreachable")

    monkeypatch.setattr(provider, "cancel", _raise)

    succeeded = async_tasks.cancel_upstream(db, task, provider)

    assert succeeded is False
    assert async_tasks.find_for_job(db, job.id) is None


def test_a_render_past_its_deadline_keeps_polling(
    db: Session, funded: User, provider: _AsyncProvider
) -> None:
    """The upstream always answers succeeded or failed. A slow render must
    not be cancelled just because the sweeper lease elapsed."""
    job = _suspended(db, funded)
    task = _due(db, job.id)
    expired = utcnow() - dt.timedelta(seconds=1)
    task.deadline_at = expired
    db.flush()

    async_polling.poll_once(db)

    assert provider.cancelled == []
    assert provider.polls == ["ext_1"]
    attempts = list(db.scalars(select(ProviderAttempt).where(ProviderAttempt.job_id == job.id)))
    assert attempts[0].status == ProviderAttemptStatus.RUNNING
    task = async_tasks.find_for_job(db, job.id)
    assert task is not None
    assert task.poll_count == 1
    assert task.claimed_at is None
    assert task.deadline_at > utcnow()
    db.refresh(job)
    assert job.status == JobStatus.RUNNING


def test_a_dead_upstream_that_never_answers_is_eventually_given_up_on(
    db: Session, funded: User, provider: _AsyncProvider
) -> None:
    """A render whose upstream never says succeeded or failed — just `pending`
    forever — must not tie up the job's reservation forever. `deadline_at` is
    renewed every tick specifically so it can never trip on its own here;
    `MAX_POLL_DURATION_SECONDS`, measured from the immutable `created_at`, is
    the only thing that can end this."""
    job = _suspended(db, funded)

    def _stale_and_due() -> AsyncProviderTask:
        task = _due(db, job.id)
        task.created_at = utcnow() - dt.timedelta(seconds=async_tasks.MAX_POLL_DURATION_SECONDS + 1)
        db.flush()
        return task

    _stale_and_due()
    for _ in range(10):
        if async_tasks.find_for_job(db, job.id) is None:
            break
        async_polling.poll_once(db)
        if async_tasks.find_for_job(db, job.id) is not None:
            _stale_and_due()
    else:
        pytest.fail("job never reached a terminal state")

    db.refresh(job)
    assert JobStatus(job.status).is_terminal
    account = credits_service.get_or_create_account(db, funded.id)
    assert account.reserved_balance == 0
    failed_attempts = list(
        db.scalars(
            select(ProviderAttempt).where(
                ProviderAttempt.job_id == job.id,
                ProviderAttempt.status == ProviderAttemptStatus.FAILED,
            )
        )
    )
    assert len(failed_attempts) >= 1


def test_a_render_past_its_deadline_still_settles_when_upstream_finishes(
    db: Session, funded: User, provider: _AsyncProvider
) -> None:
    job = _suspended(db, funded)
    provider.outcomes = [_finished()]
    task = _due(db, job.id)
    task.deadline_at = utcnow() - dt.timedelta(seconds=1)
    db.flush()

    async_polling.poll_once(db)

    db.refresh(job)
    assert job.status == JobStatus.SUCCEEDED
    assert async_tasks.find_for_job(db, job.id) is None
    assert provider.cancelled == []
    attempt = db.scalar(select(ProviderAttempt).where(ProviderAttempt.job_id == job.id))
    assert attempt is not None and attempt.status == ProviderAttemptStatus.SUCCEEDED


def test_two_ticks_racing_for_one_task_produce_exactly_one_winner(
    db: Session, funded: User, provider: _AsyncProvider
) -> None:
    """Both resuming would run the workflow twice and settle the job twice."""
    job = _suspended(db, funded)
    _due(db, job.id)

    first = async_tasks.claim_due(db)
    second = async_tasks.claim_due(db)

    assert [task.job_id for task in first] == [job.id]
    assert second == []


def test_a_claim_left_behind_by_a_dead_worker_is_taken_over(
    db: Session, funded: User, provider: _AsyncProvider
) -> None:
    """A worker killed mid-tick must not strand the render forever."""
    job = _suspended(db, funded)
    task = _due(db, job.id)
    task.claimed_at = utcnow() - async_tasks.CLAIM_LEASE - dt.timedelta(minutes=1)
    db.flush()

    assert [row.job_id for row in async_tasks.claim_due(db)] == [job.id]


def test_a_job_settled_elsewhere_drops_its_task_without_resuming(
    db: Session, funded: User, provider: _AsyncProvider
) -> None:
    """The expiry sweeper and admin actions can both reach a terminal state
    while a render is in flight."""
    job = _suspended(db, funded)
    jobs_service.settle_release(db, job, reason="expired")
    sm.transition(db, job.id, JobStatus.EXPIRED, failure_code="JOB_EXPIRED")
    db.commit()
    _due(db, job.id)

    async_polling.poll_once(db)

    assert async_tasks.find_for_job(db, job.id) is None
    assert provider.polls == []
    db.refresh(job)
    assert job.status == JobStatus.EXPIRED


def test_a_capability_deleted_mid_render_fails_the_job_rather_than_hanging(
    db: Session, funded: User, provider: _AsyncProvider, monkeypatch: pytest.MonkeyPatch
) -> None:
    job = _suspended(db, funded)
    monkeypatch.setattr(router, "build_catalog", lambda session: {})
    _due(db, job.id)

    async_polling.poll_once(db)

    db.refresh(job)
    assert JobStatus(job.status).is_terminal
    assert async_tasks.find_for_job(db, job.id) is None
    account = credits_service.get_or_create_account(db, funded.id)
    assert account.reserved_balance == 0


def test_the_poll_timeout_stays_under_the_stale_job_sweep(db: Session) -> None:
    """Otherwise the sweeper would expire a job that is still legitimately
    rendering, releasing credits for work that then succeeds."""
    from app.workers import tasks

    assert dt.timedelta(seconds=async_tasks.TASK_TIMEOUT_SECONDS) < tasks.STALE_JOB_TIMEOUT


def test_old_and_new_reference_checkpoint_shapes_both_resume() -> None:
    legacy = async_polling._request_from(  # type: ignore[attr-defined]
        {
            "job_id": "job-old",
            "operation": "image_to_video",
            "quality_tier": "standard",
            "prompt": "legacy",
            "reference_object_keys": ["legacy.png"],
        }
    )
    assert legacy.reference_object_keys == ["legacy.png"]

    current = async_polling._request_from(  # type: ignore[attr-defined]
        {
            "job_id": "job-new",
            "operation": "video_to_video",
            "quality_tier": "standard",
            "prompt": "current",
            "references": [{"object_key": "motion.mp4", "media_type": "video", "frame_type": None}],
        }
    )
    assert current.references[0].object_key == "motion.mp4"
    assert current.references[0].media_type == "video"
