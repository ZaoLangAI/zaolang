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
from tests.fake_providers import FORCE_FAILURE_MARKER

pytestmark = pytest.mark.usefixtures("fake_media_catalog")


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


def test_a_broker_outage_after_commit_releases_the_reservation(
    client: TestClient, db: Session, funded: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The job row and its reservation are committed before the Celery task is
    dispatched — if the broker itself is unreachable at that point, the
    reservation must come back immediately rather than sitting stuck until
    `expire_stale_jobs` notices roughly half an hour later."""

    def _unreachable_broker(_job: GenerationJob) -> None:
        raise RuntimeError("broker unreachable")

    monkeypatch.setattr(tasks, "dispatch_generation", _unreachable_broker)
    before = credits_service.get_or_create_account(db, funded.id).available_balance

    response = client.post(
        "/v1/generation-jobs",
        json={
            "operation": "text_to_image",
            "quality_tier": "standard",
            "params": {"prompt": "海边的黄昏，长镜头", "aspect_ratio": "16:9"},
        },
        headers=auth_header(funded),
    )
    assert response.status_code == 503, response.text

    job = db.scalar(
        select(GenerationJob)
        .where(GenerationJob.user_id == funded.id)
        .order_by(GenerationJob.created_at.desc())
    )
    assert job is not None
    assert job.status == JobStatus.FAILED
    assert job.failure_code == "ENQUEUE_FAILED"

    after = credits_service.get_or_create_account(db, funded.id).available_balance
    assert after == before
    assert _ledger(db, funded, LedgerEntryType.RELEASE)


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


def _park_awaiting_input(db: Session, job: GenerationJob) -> None:
    from app.domain.jobs import input_requests

    if job.status == JobStatus.CREATED:
        sm.transition(db, job.id, JobStatus.QUEUED)
    if job.status == JobStatus.QUEUED:
        sm.transition(db, job.id, JobStatus.RUNNING)
    if job.status == JobStatus.RUNNING:
        sm.transition(db, job.id, JobStatus.AWAITING_INPUT)
    input_requests.suspend(
        db,
        job_id=job.id,
        node_id="planning",
        checkpoint={
            "kind": "input_request",
            "output_key": "plan",
            "questions": [{"id": "scene", "kind": "free_text", "prompt": "?", "options": []}],
            "state": {},
        },
    )


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


def test_cancel_an_awaiting_input_job_releases_immediately_through_the_api(
    client: TestClient, db: Session, funded: User
) -> None:
    """The stuck-job shape: flag set, parked on a question, nobody polling."""
    from app.domain.jobs import input_requests

    job = _submit(db, funded)
    _park_awaiting_input(db, job)
    account = credits_service.get_or_create_account(db, funded.id)
    before = account.available_balance + job.reserved_credits

    response = client.post(f"/v1/generation-jobs/{job.id}/cancel", headers=auth_header(funded))

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == JobStatus.CANCELLED
    assert body["cancel_requested"] is True
    db.refresh(job)
    db.refresh(account)
    assert job.status == JobStatus.CANCELLED
    assert job.finished_at is not None
    assert input_requests.find_for_job(db, job.id) is None
    assert account.available_balance == before
    assert account.reserved_balance == 0
    assert _ledger(db, funded, LedgerEntryType.RELEASE)


def test_cancel_a_created_job_is_honoured_immediately(
    client: TestClient, db: Session, funded: User
) -> None:
    job = _submit(db, funded)
    assert job.status == JobStatus.CREATED

    response = client.post(f"/v1/generation-jobs/{job.id}/cancel", headers=auth_header(funded))

    assert response.status_code == 200
    assert response.json()["status"] == JobStatus.CANCELLED
    db.refresh(job)
    assert job.status == JobStatus.CANCELLED


def test_cancel_a_queued_job_is_a_request_until_the_worker_honours(
    client: TestClient, db: Session, funded: User
) -> None:
    job = _submit(db, funded)
    sm.transition(db, job.id, JobStatus.QUEUED)

    response = client.post(f"/v1/generation-jobs/{job.id}/cancel", headers=auth_header(funded))

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == JobStatus.QUEUED
    assert body["cancel_requested"] is True
    assert any(event["message"] == "已收到取消请求" for event in body["events"])


def test_answering_a_cancelled_awaiting_input_job_does_not_resume(
    db: Session, funded: User
) -> None:
    from app.domain.jobs import input_requests

    job = _submit(db, funded)
    _park_awaiting_input(db, job)
    sm.request_cancel(db, job.id)

    result = input_requests.answer(db, job, {"scene": "indoor"})

    db.refresh(job)
    assert result.status == JobStatus.CANCELLED
    assert job.status == JobStatus.CANCELLED
    assert input_requests.find_for_job(db, job.id) is None


def test_expire_stale_input_requests_honours_a_pending_cancel(
    db: Session, funded: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A cancel on a question that has not timed out must not wait 6 hours,
    and must become `cancelled` rather than `expired`."""
    from app.domain.jobs import input_requests

    job = _submit(db, funded)
    _park_awaiting_input(db, job)
    sm.request_cancel(db, job.id)
    account = credits_service.get_or_create_account(db, funded.id)
    before = account.available_balance + job.reserved_credits

    @contextmanager
    def fake_session_scope():
        yield db

    monkeypatch.setattr(tasks, "session_scope", fake_session_scope)
    assert tasks.expire_stale_input_requests.run() == 1

    db.refresh(job)
    db.refresh(account)
    assert job.status == JobStatus.CANCELLED
    assert job.failure_code is None
    assert account.available_balance == before
    assert input_requests.find_for_job(db, job.id) is None


def test_cancel_during_sync_submit_is_honoured_before_quality(
    db: Session, funded: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.fake_providers import REGISTRY

    job = _submit(db, funded)
    for provider in REGISTRY.values():
        provider_cls = type(provider)
        original = provider_cls.submit

        def _submit_and_cancel(self: object, request: object, *, _original=original) -> object:
            sm.request_cancel(db, job.id)
            return _original(self, request)

        # Patched on the class, not the instance: `REGISTRY`'s providers are
        # process-wide singletons shared by every test in this session (see
        # `tests.fake_providers.get_provider`'s own doc comment for why
        # patching an instance instead would permanently corrupt this
        # singleton for every later test).
        monkeypatch.setattr(provider_cls, "submit", _submit_and_cancel)

    outcome = pipeline.run_generation_pipeline(db, job.id)

    assert outcome.status == JobStatus.CANCELLED
    db.refresh(job)
    assert job.status == JobStatus.CANCELLED
    assert not _ledger(db, funded, LedgerEntryType.CAPTURE)


@pytest.mark.parametrize(
    "operation",
    [
        Operation.TEXT_TO_IMAGE,
        Operation.IMAGE_TO_IMAGE,
        Operation.TEXT_TO_VIDEO,
        Operation.AUDIO_GENERATION,
    ],
)
def test_honor_user_cancel_is_shared_across_operations(
    db: Session, funded: User, operation: str
) -> None:
    from app.domain.jobs import input_requests
    from app.domain.jobs.cancellation import honor_user_cancel

    job = _submit(db, funded, operation=operation)
    _park_awaiting_input(db, job)
    sm.request_cancel(db, job.id)

    job = honor_user_cancel(db, job)

    assert job.status == JobStatus.CANCELLED
    assert input_requests.find_for_job(db, job.id) is None
    assert _ledger(db, funded, LedgerEntryType.RELEASE)


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
                unit_cost_micro_usd=200000,
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


class _DispatchRecorder:
    """Captures both `delay` (video/audio/analysis) and image `apply_async`."""

    def __init__(self, label: str) -> None:
        self.label = label
        self.calls: list[dict[str, object]] = []

    def delay(self, job_id: str) -> None:
        self.calls.append({"method": "delay", "job_id": job_id})

    def apply_async(self, args: tuple[object, ...], **kwargs: object) -> None:
        self.calls.append({"method": "apply_async", "args": args, **kwargs})


def test_video_work_is_dispatched_to_the_long_queue(monkeypatch) -> None:
    """A four-minute render on the image queue would block every quick job
    behind it."""
    image = _DispatchRecorder("image")
    video = _DispatchRecorder("video")
    video_analysis = _DispatchRecorder("video_analysis")
    monkeypatch.setattr(tasks, "run_generation", image)
    monkeypatch.setattr(tasks, "run_video_generation", video)
    monkeypatch.setattr(tasks, "run_video_analysis", video_analysis)

    tasks.dispatch_generation(GenerationJob(id="job_x", operation=Operation.TEXT_TO_VIDEO.value))
    tasks.dispatch_generation(GenerationJob(id="job_y", operation=Operation.TEXT_TO_IMAGE.value))
    tasks.dispatch_generation(GenerationJob(id="job_z", operation=Operation.VIDEO_ANALYSIS.value))

    assert video.calls == [{"method": "delay", "job_id": "job_x"}]
    assert video_analysis.calls == [{"method": "delay", "job_id": "job_z"}]
    assert image.calls == [
        {
            "method": "apply_async",
            "args": ("job_y",),
            "soft_time_limit": 420,
            "time_limit": 480,
        }
    ]


def test_image_dispatch_stretches_time_limit_for_character_views(monkeypatch) -> None:
    """A multi-view character job loops generate+quality in one task."""
    image = _DispatchRecorder("image")
    monkeypatch.setattr(tasks, "run_generation", image)

    two = GenerationJob(
        id="job_two",
        operation=Operation.IMAGE_TO_IMAGE.value,
        request_json={
            "asset_kind": "character",
            "character_views": ["side", "back"],
        },
    )
    three = GenerationJob(
        id="job_three",
        operation=Operation.TEXT_TO_IMAGE.value,
        request_json={
            "asset_kind": "character",
            "character_views": ["front", "side", "back"],
        },
    )
    tasks.dispatch_generation(two)
    tasks.dispatch_generation(three)

    assert image.calls == [
        {
            "method": "apply_async",
            "args": ("job_two",),
            "soft_time_limit": 600,
            "time_limit": 720,
        },
        {
            "method": "apply_async",
            "args": ("job_three",),
            "soft_time_limit": 780,
            "time_limit": 960,
        },
    ]


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


def test_job_response_exposes_which_character_a_job_linked_to(
    client: TestClient, db: Session, author: User
) -> None:
    """`execute_asset_output_link` records the target it actually used onto
    the job row (see `app.workflows.nodes`) — the script studio's "返回文案
    创作" jump-back reads this field to auto-relink without the user
    re-picking from `ScriptLinkPicker`."""
    from app.domain.characters import service as characters_service

    character = characters_service.create_character(
        db,
        user_id=author.id,
        name="林夏",
        description=None,
        reference_asset_ids=[],
        voice_description=None,
    )
    job = make_job(db, author, status=JobStatus.SUCCEEDED)
    job.linked_character_id = character.id
    db.flush()

    response = client.get(f"/v1/generation-jobs/{job.id}", headers=auth_header(author))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["linked_character_id"] == character.id
    assert body["linked_scene_id"] is None


def test_job_response_exposes_which_scene_a_job_linked_to(
    client: TestClient, db: Session, author: User
) -> None:
    from app.domain.scenes import service as scenes_service

    scene = scenes_service.create_scene(
        db, user_id=author.id, name="深夜便利店", description=None, reference_asset_ids=[]
    )
    job = make_job(db, author, status=JobStatus.SUCCEEDED)
    job.linked_scene_id = scene.id
    db.flush()

    response = client.get(f"/v1/generation-jobs/{job.id}", headers=auth_header(author))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["linked_scene_id"] == scene.id
    assert body["linked_character_id"] is None


def _enable_video_analysis(session: Session, actor: User) -> None:
    from app.platform_config import service as config_service
    from app.platform_config.schemas import FeatureFlags

    value = config_service.get_typed(session, "feature_flags", FeatureFlags).model_dump(
        mode="json"
    )
    value["video_analysis_enabled"] = True
    config_service.set_value(session, "feature_flags", value, actor_user_id=actor.id, note="test")


def _reference_video_asset(session: Session, owner: User, *, duration_ms: int = 30_000) -> Asset:
    asset = Asset(
        owner_user_id=owner.id,
        object_key=f"test/{new_id('obj')}.mp4",
        media_type=MediaType.VIDEO,
        mime_type="video/mp4",
        size_bytes=1024,
        duration_ms=duration_ms,
        checksum_sha256="c" * 64,
        role=AssetRole.GENERATION_REFERENCE,
        moderation_status=ModerationStatus.APPROVED,
        visibility=Visibility.PRIVATE,
    )
    session.add(asset)
    session.flush()
    return asset


def test_video_analysis_is_refused_until_its_feature_flag_is_enabled(
    client: TestClient, db: Session, funded: User
) -> None:
    video = _reference_video_asset(db, funded)
    db.commit()

    blocked = client.post(
        "/v1/generation-jobs",
        json={
            "operation": "video_analysis",
            "quality_tier": "standard",
            "params": {"reference_asset_ids": [video.id]},
        },
        headers=auth_header(funded),
    )
    assert blocked.status_code == 422
    assert blocked.json()["error"]["code"] == "VALIDATION_FAILED"

    _enable_video_analysis(db, funded)
    db.commit()
    allowed = client.post(
        "/v1/generation-jobs",
        json={
            "operation": "video_analysis",
            "quality_tier": "standard",
            "params": {"reference_asset_ids": [video.id]},
        },
        headers=auth_header(funded),
    )
    assert allowed.status_code == 202, allowed.text
    assert allowed.json()["operation"] == "video_analysis"


def test_video_analysis_settles_into_structured_analysis_and_the_operation_filtered_history(
    client: TestClient, db: Session, funded: User
) -> None:
    """Mirrors `文案创作`'s history pattern: the analysis result rides on the
    job itself, and the C-end history panel lists only this tool's own jobs
    via `operation=video_analysis` without needing a `draft_id`."""
    _enable_video_analysis(db, funded)
    video = _reference_video_asset(db, funded)
    db.commit()

    result = jobs_service.submit(
        db,
        user_id=funded.id,
        operation=Operation.VIDEO_ANALYSIS,
        quality_tier=QualityTier.STANDARD,
        params={"reference_asset_ids": [video.id], "prompt": "重点关注运镜"},
        idempotency_key=new_id("idk"),
    )
    other = _submit(db, funded)

    outcome = pipeline.run_generation_pipeline(db, result.job.id)
    assert outcome.status == JobStatus.SUCCEEDED
    assert outcome.asset_id is None
    assert outcome.result_json is not None

    db.refresh(result.job)
    assert result.job.analysis_result_json is not None
    assert result.job.analysis_result_json["composed_prompt"]

    body = client.get(
        f"/v1/generation-jobs/{result.job.id}", headers=auth_header(funded)
    ).json()
    assert body["analysis"]["composed_prompt"] == result.job.analysis_result_json["composed_prompt"]
    assert body["analysis"]["shots"][0]["camera_movement"]
    assert body["output_asset_id"] is None
    # The one job type whose *input* (not output) is worth echoing back, so
    # the studio and history panel can replay the source video (see
    # `GenerationJobResponse.reference_url`).
    assert body["reference_url"]

    listed = client.get(
        "/v1/generation-jobs",
        params={"operation": "video_analysis"},
        headers=auth_header(funded),
    ).json()
    ids = {item["id"] for item in listed["items"]}
    assert result.job.id in ids
    assert other.id not in ids
