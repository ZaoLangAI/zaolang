"""End-to-end generation job lifecycle.

The pipeline is invoked inline rather than through a broker: Celery adds
scheduling, not behaviour, and running it inline lets each test assert on the
ledger and the event stream in the same transaction.
"""

from __future__ import annotations

import datetime as dt
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents import router
from app.domain.credits import service as credits_service
from app.domain.errors import CreditsExceedBudget, InsufficientCredits
from app.domain.jobs import service as jobs_service
from app.domain.jobs import state_machine as sm
from app.models import (
    Asset,
    CreditLedgerEntry,
    GenerationJob,
    GenerationWorkflowTemplate,
    JobEvent,
    ProviderAttempt,
    User,
)
from app.models.base import new_id, utcnow
from app.models.enums import (
    AssetRole,
    JobOrigin,
    JobStatus,
    LedgerEntryType,
    MediaType,
    ModerationStatus,
    Operation,
    QualityTier,
    Visibility,
)
from app.workers import pipeline, tasks
from tests.conftest import auth_header
from tests.factories import make_job
from tests.fake_provider_catalog import build_fake_catalog
from tests.fake_providers import FORCE_FAILURE_MARKER


@pytest.fixture(autouse=True)
def _inject_test_media_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    """Generation tests opt into fake providers; production never registers them."""
    monkeypatch.setattr(router, "build_catalog", lambda session: build_fake_catalog())


@pytest.fixture
def funded(db: Session, author: User) -> User:
    credits_service.grant(db, author.id, 5_000, idempotency_key=new_id("grant"))
    db.flush()
    return author


def _submit(
    db: Session,
    user: User,
    *,
    prompt: str = "海边的黄昏，长镜头",
    operation: str = Operation.TEXT_TO_IMAGE,
    tier: str = QualityTier.STANDARD,
    key: str | None = None,
    max_credits: int | None = None,
) -> GenerationJob:
    result = jobs_service.submit(
        db,
        user_id=user.id,
        operation=operation,
        quality_tier=tier,
        params={"prompt": prompt, "aspect_ratio": "16:9"},
        idempotency_key=key or new_id("idk"),
        max_credits=max_credits,
    )
    return result.job


def _ledger(db: Session, user: User, entry_type: str) -> list[CreditLedgerEntry]:
    account = credits_service.get_or_create_account(db, user.id)
    return list(
        db.scalars(
            select(CreditLedgerEntry).where(
                CreditLedgerEntry.account_id == account.id,
                CreditLedgerEntry.type == entry_type,
            )
        )
    )


def test_a_quote_is_available_before_anything_is_reserved(db: Session, funded: User) -> None:
    before = credits_service.get_or_create_account(db, funded.id).available_balance
    priced = jobs_service.quote_for(
        db, operation=Operation.TEXT_TO_IMAGE, quality_tier=QualityTier.STANDARD
    )
    assert priced.credits > 0
    after = credits_service.get_or_create_account(db, funded.id).available_balance
    assert before == after


def test_submitting_reserves_exactly_the_quoted_amount(db: Session, funded: User) -> None:
    account = credits_service.get_or_create_account(db, funded.id)
    before = account.available_balance

    job = _submit(db, funded)

    db.refresh(account)
    assert account.available_balance == before - job.quoted_credits
    assert account.reserved_balance == job.quoted_credits


def test_a_submission_without_enough_credits_is_refused(db: Session, author: User) -> None:
    with pytest.raises(InsufficientCredits):
        _submit(db, author)


def test_a_budget_cap_is_enforced_before_reserving(db: Session, funded: User) -> None:
    with pytest.raises(CreditsExceedBudget):
        _submit(db, funded, max_credits=1)

    account = credits_service.get_or_create_account(db, funded.id)
    assert account.reserved_balance == 0


def test_a_sandbox_submit_quotes_but_does_not_reserve(db: Session, author: User) -> None:
    """Product sandbox still records what the run would have cost, but never
    touches the ledger — even when the operator has a zero balance."""
    result = jobs_service.submit(
        db,
        user_id=author.id,
        operation=Operation.TEXT_TO_IMAGE,
        quality_tier=QualityTier.STANDARD,
        params={"prompt": "海边的黄昏，长镜头", "aspect_ratio": "16:9"},
        idempotency_key=new_id("idk"),
        origin=JobOrigin.SANDBOX,
    )
    job = result.job
    assert job.origin == JobOrigin.SANDBOX
    assert job.quoted_credits > 0
    assert job.reserved_credits == 0
    assert not _ledger(db, author, LedgerEntryType.RESERVE)

    jobs_service.settle_success(db, job, actual_credits=job.quoted_credits)
    assert job.actual_credits == 0
    assert not _ledger(db, author, LedgerEntryType.CAPTURE)

    jobs_service.settle_release(db, job, reason="failed")
    assert not _ledger(db, author, LedgerEntryType.RELEASE)


def test_the_consumer_job_list_hides_sandbox_runs_but_keeps_user_jobs(
    client: TestClient, db: Session, funded: User
) -> None:
    """A C-end list must keep showing the caller's own submissions after the
    sandbox origin filter landed — hiding everything would be a silent
    product break."""
    user_job = _submit(db, funded)
    sandbox = jobs_service.submit(
        db,
        user_id=funded.id,
        operation=Operation.TEXT_TO_IMAGE,
        quality_tier=QualityTier.STANDARD,
        params={"prompt": "沙盒不应出现在 C 端列表", "aspect_ratio": "16:9"},
        idempotency_key=new_id("idk"),
        origin=JobOrigin.SANDBOX,
    ).job

    listed = client.get("/v1/generation-jobs", headers=auth_header(funded)).json()
    ids = {item["id"] for item in listed["items"]}
    assert user_job.id in ids
    assert sandbox.id not in ids
    own = client.get(f"/v1/generation-jobs/{user_job.id}", headers=auth_header(funded))
    hidden = client.get(f"/v1/generation-jobs/{sandbox.id}", headers=auth_header(funded))
    assert own.status_code == 200
    assert hidden.status_code == 404


def test_the_same_idempotency_key_produces_one_job_and_one_reservation(
    db: Session, funded: User
) -> None:
    """A double-tapped submit button must not reserve twice."""
    key = new_id("idk")
    first = _submit(db, funded, key=key)
    account = credits_service.get_or_create_account(db, funded.id)
    reserved_after_first = account.reserved_balance

    result = jobs_service.submit(
        db,
        user_id=funded.id,
        operation=Operation.TEXT_TO_IMAGE,
        quality_tier=QualityTier.STANDARD,
        params={"prompt": "海边的黄昏，长镜头", "aspect_ratio": "16:9"},
        idempotency_key=key,
    )

    assert result.replayed is True
    assert result.job.id == first.id
    db.refresh(account)
    assert account.reserved_balance == reserved_after_first


def test_a_successful_run_captures_once_and_returns_the_difference(
    db: Session, funded: User
) -> None:
    job = _submit(db, funded)
    account = credits_service.get_or_create_account(db, funded.id)
    before_available = account.available_balance

    outcome = pipeline.run_generation_pipeline(db, job.id)
    assert outcome.status == JobStatus.SUCCEEDED

    db.refresh(job)
    db.refresh(account)
    assert job.actual_credits is not None and job.actual_credits <= job.reserved_credits
    assert account.reserved_balance == 0
    # Whatever was reserved but not spent comes back.
    assert account.available_balance == before_available + (
        job.reserved_credits - job.actual_credits
    )
    assert len(_ledger(db, funded, LedgerEntryType.CAPTURE)) == 1


def test_a_successful_run_produces_an_asset_with_provenance(db: Session, funded: User) -> None:
    job = _submit(db, funded)
    outcome = pipeline.run_generation_pipeline(db, job.id)

    assert outcome.asset_id is not None
    from app.domain.media import service as media_service

    manifest = media_service.provenance_for(db, outcome.asset_id)
    assert manifest is not None
    assert manifest.generation_job_id == job.id


def test_a_rejected_prompt_never_reaches_a_provider(db: Session, funded: User) -> None:
    """Safety holds a hard veto, so no credits may be spent and no provider
    attempt may exist."""
    job = _submit(db, funded, prompt="生成未成年人的亲密画面")
    account = credits_service.get_or_create_account(db, funded.id)
    before = account.available_balance + job.reserved_credits

    outcome = pipeline.run_generation_pipeline(db, job.id)

    assert outcome.status == JobStatus.FAILED
    assert outcome.failure_code == "MODERATION_REJECTED"
    attempts = list(db.scalars(select(ProviderAttempt).where(ProviderAttempt.job_id == job.id)))
    assert attempts == []

    db.refresh(account)
    assert account.reserved_balance == 0
    assert account.available_balance == before
    assert not _ledger(db, funded, LedgerEntryType.CAPTURE)


def test_a_needs_review_prompt_still_generates_but_opens_a_queue_item(
    db: Session, funded: User
) -> None:
    """`needs_review` is uncertainty, not a veto: generation still runs, but a
    human now has a real row to look at instead of the verdict being
    recorded and never followed up on."""
    from app.models import ModerationQueueItem
    from app.models.enums import ModerationStage, ModerationStatus

    job = _submit(db, funded, prompt="血腥暴力的战场场景")

    outcome = pipeline.run_generation_pipeline(db, job.id)

    assert outcome.status != JobStatus.FAILED

    item = db.scalar(
        select(ModerationQueueItem).where(
            ModerationQueueItem.subject_type == "generation_job",
            ModerationQueueItem.subject_id == job.id,
            ModerationQueueItem.stage == ModerationStage.PRE_GENERATION,
        )
    )
    assert item is not None
    assert item.status == ModerationStatus.NEEDS_REVIEW
    assert item.reason_code == "SENSITIVE_CONTENT"


def test_a_provider_failure_releases_the_full_reservation(db: Session, funded: User) -> None:
    job = _submit(db, funded, prompt=f"海边黄昏 {FORCE_FAILURE_MARKER}")
    account = credits_service.get_or_create_account(db, funded.id)
    before = account.available_balance + job.reserved_credits

    outcome = pipeline.run_generation_pipeline(db, job.id)

    assert outcome.status == JobStatus.FAILED
    db.refresh(account)
    assert account.reserved_balance == 0
    assert account.available_balance == before
    assert len(_ledger(db, funded, LedgerEntryType.RELEASE)) == 1


def test_a_failing_route_is_retried_before_giving_up(db: Session, funded: User) -> None:
    job = _submit(db, funded, prompt=f"海边黄昏 {FORCE_FAILURE_MARKER}")
    pipeline.run_generation_pipeline(db, job.id)

    attempts = list(db.scalars(select(ProviderAttempt).where(ProviderAttempt.job_id == job.id)))
    assert len(attempts) == pipeline.MAX_PROVIDER_ATTEMPTS
    assert [a.attempt_number for a in attempts] == [1, 2]


def test_a_cancelled_job_is_released_and_not_charged(db: Session, funded: User) -> None:
    job = _submit(db, funded)
    sm.request_cancel(db, job.id)
    account = credits_service.get_or_create_account(db, funded.id)
    before = account.available_balance + job.reserved_credits

    outcome = pipeline.run_generation_pipeline(db, job.id)

    assert outcome.status == JobStatus.CANCELLED
    db.refresh(account)
    assert account.available_balance == before
    assert not _ledger(db, funded, LedgerEntryType.CAPTURE)


def test_events_carry_a_strictly_increasing_sequence(db: Session, funded: User) -> None:
    """SSE reconnection depends on this: `Last-Event-ID` is meaningless if
    sequences can repeat or go backwards."""
    job = _submit(db, funded)
    pipeline.run_generation_pipeline(db, job.id)

    sequences = [
        e.sequence
        for e in db.scalars(
            select(JobEvent).where(JobEvent.job_id == job.id).order_by(JobEvent.sequence)
        )
    ]
    assert sequences == sorted(sequences)
    assert len(sequences) == len(set(sequences))
    assert sequences[0] == 1


def test_a_reconnecting_client_receives_only_the_events_it_missed(
    db: Session, funded: User
) -> None:
    job = _submit(db, funded)
    pipeline.run_generation_pipeline(db, job.id)

    everything = sm.events_since(db, job.id, 0)
    assert len(everything) > 2

    midpoint = everything[1].sequence
    resumed = sm.events_since(db, job.id, midpoint)
    assert [e.sequence for e in resumed] == [
        e.sequence for e in everything if e.sequence > midpoint
    ]


def test_a_terminal_job_is_not_run_again(db: Session, funded: User) -> None:
    """Celery redelivers on worker loss; a second run must not double-charge."""
    job = _submit(db, funded)
    pipeline.run_generation_pipeline(db, job.id)
    captures_before = len(_ledger(db, funded, LedgerEntryType.CAPTURE))

    again = pipeline.run_generation_pipeline(db, job.id)

    assert again.status == JobStatus.SUCCEEDED
    assert len(_ledger(db, funded, LedgerEntryType.CAPTURE)) == captures_before


def test_a_stale_job_is_expired_and_its_credits_returned(
    db: Session, funded: User, monkeypatch
) -> None:
    """A worker that dies mid-flight would otherwise strand the reservation
    forever."""
    job = _submit(db, funded)
    job.updated_at = utcnow() - tasks.STALE_JOB_TIMEOUT - dt.timedelta(minutes=1)
    db.flush()

    account = credits_service.get_or_create_account(db, funded.id)
    before = account.available_balance + job.reserved_credits

    @contextmanager
    def fake_session_scope():
        yield db

    monkeypatch.setattr(tasks, "session_scope", fake_session_scope)
    assert tasks.expire_stale_jobs.run() == 1

    db.refresh(job)
    db.refresh(account)
    assert job.status == JobStatus.EXPIRED
    assert account.reserved_balance == 0
    assert account.available_balance == before


def test_stale_sweeper_does_not_expire_a_live_external_task(
    db: Session, funded: User, monkeypatch
) -> None:
    from app.domain.jobs import async_tasks

    job = _submit(db, funded, operation=Operation.TEXT_TO_VIDEO)
    sm.transition(db, job.id, JobStatus.QUEUED)
    sm.transition(db, job.id, JobStatus.RUNNING)
    async_tasks.suspend(
        db,
        job_id=job.id,
        node_id="provider_generate",
        checkpoint={
            "capability_name": "ep_h3:text_to_video",
            "external_task_id": "task_live",
            "request": {},
            "state": {},
        },
    )
    job.updated_at = utcnow() - tasks.STALE_JOB_TIMEOUT - dt.timedelta(minutes=1)
    db.flush()

    @contextmanager
    def fake_session_scope():
        yield db

    monkeypatch.setattr(tasks, "session_scope", fake_session_scope)
    assert tasks.expire_stale_jobs.run() == 0
    db.refresh(job)
    assert job.status == JobStatus.RUNNING


def test_stale_sweeper_does_not_expire_a_task_whose_own_lease_has_also_gone_stale(
    db: Session, funded: User, monkeypatch
) -> None:
    """A dead Beat starves both this sweep and the poller alike, so when Beat
    finally comes back the task's own `deadline_at` lease is just as overdue
    as `job.updated_at` — that staleness is evidence Beat was down, not that
    the render died. `expire_stale_jobs` used to key its exclusion on
    `deadline_at > moment`, so this exact shape used to race the first
    `poll_async_provider_tasks` tick after recovery and could settle an
    upstream that had actually already succeeded as `expired` instead —
    exactly what happened to a real job."""
    from app.domain.jobs import async_tasks

    job = _submit(db, funded, operation=Operation.TEXT_TO_VIDEO)
    sm.transition(db, job.id, JobStatus.QUEUED)
    sm.transition(db, job.id, JobStatus.RUNNING)
    async_tasks.suspend(
        db,
        job_id=job.id,
        node_id="provider_generate",
        checkpoint={
            "capability_name": "ep_h3:text_to_video",
            "external_task_id": "task_live",
            "request": {},
            "state": {},
        },
    )
    task = async_tasks.find_for_job(db, job.id)
    assert task is not None
    task.deadline_at = utcnow() - dt.timedelta(hours=6)
    job.updated_at = utcnow() - tasks.STALE_JOB_TIMEOUT - dt.timedelta(minutes=1)
    db.flush()

    @contextmanager
    def fake_session_scope():
        yield db

    monkeypatch.setattr(tasks, "session_scope", fake_session_scope)
    assert tasks.expire_stale_jobs.run() == 0
    db.refresh(job)
    assert job.status == JobStatus.RUNNING
    assert async_tasks.find_for_job(db, job.id) is not None


def test_stale_sweeper_does_not_expire_a_live_input_request(
    db: Session, funded: User, monkeypatch
) -> None:
    """The `copy_generate` counterpart: `expire_stale_input_requests` owns
    this deadline, not the general sweeper — same exclusion as the external
    task above, via `WorkflowInputRequest` instead of `AsyncProviderTask`."""
    from app.domain.jobs import input_requests

    job = _submit(db, funded)
    sm.transition(db, job.id, JobStatus.QUEUED)
    sm.transition(db, job.id, JobStatus.RUNNING)
    sm.transition(db, job.id, JobStatus.AWAITING_INPUT)
    input_requests.suspend(
        db,
        job_id=job.id,
        node_id="copy",
        checkpoint={
            "kind": "input_request",
            "output_key": "copy_suggestion",
            "questions": [{"id": "scene", "kind": "free_text", "prompt": "?", "options": []}],
            "state": {},
        },
    )
    job.updated_at = utcnow() - tasks.STALE_JOB_TIMEOUT - dt.timedelta(minutes=1)
    db.flush()

    @contextmanager
    def fake_session_scope():
        yield db

    monkeypatch.setattr(tasks, "session_scope", fake_session_scope)
    assert tasks.expire_stale_jobs.run() == 0
    db.refresh(job)
    assert job.status == JobStatus.AWAITING_INPUT


def test_expire_stale_input_requests_releases_credits_for_an_unanswered_question(
    db: Session, funded: User, monkeypatch
) -> None:
    """Nobody answered in time: the job expires and the reservation comes back,
    same governance `expire_stale_jobs` gives an abandoned provider task."""
    from app.domain.jobs import input_requests

    job = _submit(db, funded)
    sm.transition(db, job.id, JobStatus.QUEUED)
    sm.transition(db, job.id, JobStatus.RUNNING)
    sm.transition(db, job.id, JobStatus.AWAITING_INPUT)
    account = credits_service.get_or_create_account(db, funded.id)
    before = account.available_balance + job.reserved_credits

    request = input_requests.suspend(
        db,
        job_id=job.id,
        node_id="copy",
        checkpoint={
            "kind": "input_request",
            "output_key": "copy_suggestion",
            "questions": [{"id": "scene", "kind": "free_text", "prompt": "?", "options": []}],
            "state": {},
        },
        now=utcnow() - dt.timedelta(seconds=input_requests.INPUT_TIMEOUT_SECONDS + 60),
    )

    @contextmanager
    def fake_session_scope():
        yield db

    monkeypatch.setattr(tasks, "session_scope", fake_session_scope)
    assert tasks.expire_stale_input_requests.run() == 1

    db.refresh(job)
    db.refresh(account)
    assert job.status == JobStatus.EXPIRED
    assert job.failure_code == "INPUT_REQUEST_EXPIRED"
    assert account.reserved_balance == 0
    assert account.available_balance == before
    assert input_requests.find_for_job(db, request.job_id) is None


def test_releasing_twice_does_not_return_the_credits_twice(db: Session, funded: User) -> None:
    """The retry paths cannot always know whether an earlier attempt settled."""
    job = _submit(db, funded)
    account = credits_service.get_or_create_account(db, funded.id)
    before = account.available_balance + job.reserved_credits

    jobs_service.settle_release(db, job, reason="first")
    jobs_service.settle_release(db, job, reason="second")

    db.refresh(account)
    assert account.available_balance == before
    assert len(_ledger(db, funded, LedgerEntryType.RELEASE)) == 1


def test_an_externally_rendered_video_reports_progress_before_it_finishes(
    db: Session, funded: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The user-visible reason the polling mechanism exists: a render handed
    to an upstream must still move the progress bar, rather than sitting on
    one status for minutes and then jumping to done."""
    from app.agents import router
    from app.domain.jobs import async_tasks
    from app.models.base import new_id as _new_id
    from app.models.enums import ProviderKind
    from app.providers.base import GenerationRequest, GenerationResult, ProviderCapability
    from app.storage.s3 import put_object
    from app.workers import async_polling

    class _SlowUpstream:
        name = "slow_video"
        kind = ProviderKind.COMMERCIAL_API

        def __init__(self) -> None:
            self.remaining_polls = 2

        def submit(self, request: GenerationRequest) -> GenerationResult:
            return GenerationResult(succeeded=False, pending=True, external_task_id="ext_slow")

        def poll(self, external_task_id: str, request: GenerationRequest) -> GenerationResult:
            if self.remaining_polls > 0:
                self.remaining_polls -= 1
                return GenerationResult(
                    succeeded=False, pending=True, external_task_id=external_task_id
                )
            put_object("generated/slow.mp4", b"video-bytes", content_type="video/mp4")
            return GenerationResult(
                succeeded=True,
                object_key="generated/slow.mp4",
                mime_type="video/mp4",
                width=1920,
                height=1080,
                duration_ms=5_000,
                cost_minor=20,
                latency_ms=90_000,
            )

        def cancel(self, external_task_id: str) -> bool:
            return True

    upstream = _SlowUpstream()
    monkeypatch.setattr(
        router,
        "build_catalog",
        lambda session: {
            "slow_video": ProviderCapability(
                name="slow_video",
                kind=ProviderKind.COMMERCIAL_API,
                operations=frozenset({Operation.TEXT_TO_VIDEO}),
                tiers=frozenset({QualityTier.STANDARD}),
                quality_prior=0.9,
                typical_latency_ms=90_000,
                unit_cost_minor=20,
                model_or_workflow="minimax-h3",
                provider_factory=lambda: upstream,
            )
        },
    )
    job = jobs_service.submit(
        db,
        user_id=funded.id,
        operation=Operation.TEXT_TO_VIDEO,
        quality_tier=QualityTier.STANDARD,
        params={"prompt": "霓虹街头", "aspect_ratio": "16:9", "duration_seconds": 5},
        idempotency_key=_new_id("idk"),
    ).job

    assert pipeline.run_generation_pipeline(db, job.id).status == JobStatus.RUNNING
    progress_before = [e.progress for e in sm.events_since(db, job.id, 0)]

    for _ in range(3):
        task = async_tasks.find_for_job(db, job.id)
        if task is None:
            break
        task.next_poll_at = utcnow() - dt.timedelta(seconds=1)
        db.flush()
        async_polling.poll_once(db)

    db.refresh(job)
    assert job.status == JobStatus.SUCCEEDED
    progress_after = [e.progress for e in sm.events_since(db, job.id, 0)]
    # At least one heartbeat landed between submission and completion.
    assert len(progress_after) > len(progress_before) + 1
    assert progress_after == sorted(progress_after)


def test_video_work_is_dispatched_to_the_long_queue(monkeypatch) -> None:
    """A four-minute render on the image queue would block every quick job
    behind it."""
    routed: list[str] = []

    class _Recorder:
        def __init__(self, label: str) -> None:
            self.label = label

        def delay(self, job_id: str) -> None:
            routed.append(self.label)

    monkeypatch.setattr(tasks, "run_generation", _Recorder("image"))
    monkeypatch.setattr(tasks, "run_video_generation", _Recorder("video"))

    tasks.dispatch_generation(GenerationJob(id="job_x", operation=Operation.TEXT_TO_VIDEO.value))
    tasks.dispatch_generation(GenerationJob(id="job_y", operation=Operation.TEXT_TO_IMAGE.value))

    assert routed == ["video", "image"]


def test_latency_specific_celery_tasks_do_not_double_bind(monkeypatch) -> None:
    """Bound task wrappers must call an undecorated body, not another task."""

    calls: list[str] = []

    @contextmanager
    def fake_session_scope():
        yield object()

    def fake_pipeline(_session, job_id: str):  # type: ignore[no-untyped-def]
        calls.append(job_id)
        return SimpleNamespace(status=JobStatus.SUCCEEDED)

    monkeypatch.setattr(tasks, "session_scope", fake_session_scope)
    monkeypatch.setattr(tasks, "run_generation_pipeline", fake_pipeline)

    assert tasks.run_video_generation.apply(args=["job_video"], throw=True).get() == "succeeded"
    assert tasks.run_audio_generation.apply(args=["job_audio"], throw=True).get() == "succeeded"
    assert calls == ["job_video", "job_audio"]


def test_missing_job_does_not_retry_celery_task(monkeypatch) -> None:
    """Orphan broker messages after a DB truncate must not burn retry slots."""

    retries: list[BaseException] = []

    @contextmanager
    def fake_session_scope():
        yield object()

    def fake_pipeline(_session, job_id: str):  # type: ignore[no-untyped-def]
        raise pipeline.JobNotFoundError(f"job {job_id} not found")

    class _Task:
        def retry(self, *, exc: BaseException, countdown: int) -> BaseException:
            retries.append(exc)
            raise RuntimeError("retry must not be called for a missing job")

    monkeypatch.setattr(tasks, "session_scope", fake_session_scope)
    monkeypatch.setattr(tasks, "run_generation_pipeline", fake_pipeline)
    monkeypatch.setattr(tasks.system_log, "emit", lambda **_kwargs: None)

    assert tasks._run_generation_task(_Task(), "job_ghost") == "missing"
    assert retries == []


def test_worker_process_init_resets_db_engine_cache(monkeypatch) -> None:
    calls: list[str] = []

    def _reset() -> None:
        calls.append("reset")

    monkeypatch.setattr("app.db.reset_engine_cache", _reset)
    from app.workers.celery_app import _reset_db_engine_after_fork

    _reset_db_engine_after_fork()
    assert calls == ["reset"]


def test_final_celery_failure_marks_job_failed_and_releases_reservation(
    db: Session, funded: User, monkeypatch
) -> None:
    job = _submit(db, funded, operation=Operation.TEXT_TO_VIDEO)

    @contextmanager
    def fake_session_scope():
        yield db

    monkeypatch.setattr(tasks, "session_scope", fake_session_scope)
    tasks._settle_worker_failure(job.id, task_id="celery_failed")

    db.refresh(job)
    assert job.status == JobStatus.FAILED
    assert job.failure_code == "WORKER_TASK_FAILED"
    assert [entry.type for entry in _ledger(db, funded, LedgerEntryType.RELEASE)] == [
        LedgerEntryType.RELEASE
    ]
    assert sm.events_since(db, job.id, 0)[-1].internal_code == "WORKER_TASK_FAILED"


def _copy_generate_template_graph() -> dict:
    """A minimal published template: `copy_generate` (follow-ups on) then `fail`.

    `fail` rather than `settle_success` for the same reason as the unit-test
    equivalent in `tests/unit/test_workflow_engine.py`: this graph only exists
    to observe the suspend/resume handoff through the real HTTP surface, and
    `fail` needs no generated asset to reach a terminal state.
    """
    return {
        "nodes": [
            {
                "id": "copy",
                "type": "copy_generate",
                "config": {"output_key": "copy_suggestion", "allow_followup_question": True},
            },
            {"id": "fail", "type": "fail", "config": {}},
        ],
        "edges": [{"id": "e1", "from": "copy", "from_port": "ok", "to": "fail"}],
    }


def test_answering_a_copy_generate_follow_up_resumes_the_job_through_the_api(
    client: TestClient, db: Session, funded: User
) -> None:
    """End-to-end through the real HTTP surface: a sparse prompt makes the
    stub copy agent ask a follow-up, `GET .../input-request` exposes it, and
    `POST .../answer` resumes the graph to its next node — the point of the
    whole HITL suspend/resume design (`app.domain.jobs.input_requests`)."""
    template = GenerationWorkflowTemplate(
        operation=Operation.TEXT_TO_IMAGE.value,
        version=1,
        name="copy_generate follow-up test",
        graph_json=_copy_generate_template_graph(),
        is_active=True,
        created_at=utcnow(),
    )
    db.add(template)
    db.flush()

    job = _submit(db, funded, prompt="一只猫")
    assert job.workflow_template_id == template.id
    # `copy_generate` only ever suspends a job that is already `RUNNING` in a
    # real template (a `provider_generate` node upstream would have made this
    # transition); done by hand here since this graph has none.
    sm.transition(db, job.id, JobStatus.QUEUED)
    sm.transition(db, job.id, JobStatus.RUNNING)

    outcome = pipeline.run_generation_pipeline(db, job.id)
    assert outcome.status == JobStatus.AWAITING_INPUT
    db.refresh(job)
    assert job.status == JobStatus.AWAITING_INPUT

    headers = auth_header(funded)
    pending = client.get(f"/v1/generation-jobs/{job.id}/input-request", headers=headers)
    assert pending.status_code == 200
    body = pending.json()
    assert body["node_id"] == "copy"
    assert [q["id"] for q in body["questions"]] == ["scene", "action"]

    answered = client.post(
        f"/v1/generation-jobs/{job.id}/answer",
        headers=headers,
        json={"answers": [{"question_id": "scene", "value": "indoor"}]},
    )
    assert answered.status_code == 200
    assert answered.json()["status"] == JobStatus.FAILED

    db.refresh(job)
    assert job.status == JobStatus.FAILED
    # The question is settled: nothing is left for a second GET to return.
    assert (
        client.get(f"/v1/generation-jobs/{job.id}/input-request", headers=headers).status_code
        == 404
    )


def test_every_queue_named_in_the_routes_actually_exists() -> None:
    """A typo here would silently send tasks to a queue nobody consumes."""
    from app.workers.celery_app import QUEUE_NAMES, celery_app

    routed = {route["queue"] for route in celery_app.conf.task_routes.values()}
    assert routed <= set(QUEUE_NAMES)
    assert celery_app.conf.task_default_queue in QUEUE_NAMES


@pytest.mark.parametrize(
    ("media_type", "mime_type"),
    [
        (MediaType.IMAGE, "image/png"),
        (MediaType.AUDIO, "audio/mpeg"),
        (MediaType.VIDEO, "video/mp4"),
    ],
)
def test_job_response_exposes_output_media_type(
    client: TestClient,
    db: Session,
    author: User,
    media_type: MediaType,
    mime_type: str,
) -> None:
    asset = Asset(
        owner_user_id=author.id,
        object_key=f"test/{new_id('obj')}",
        media_type=media_type,
        mime_type=mime_type,
        size_bytes=128,
        checksum_sha256="b" * 64,
        role=AssetRole.GENERATION_OUTPUT,
        moderation_status=ModerationStatus.APPROVED,
        visibility=Visibility.PRIVATE,
    )
    db.add(asset)
    db.flush()
    job = make_job(db, author, status=JobStatus.SUCCEEDED)
    job.output_asset_id = asset.id
    db.flush()

    response = client.get(f"/v1/generation-jobs/{job.id}", headers=auth_header(author))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["output_media_type"] == media_type.value
    assert body["output_asset_id"] == asset.id
    assert body["output_url"]
