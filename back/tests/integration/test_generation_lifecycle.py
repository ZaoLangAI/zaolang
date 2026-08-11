"""End-to-end generation job lifecycle.

The pipeline is invoked inline rather than through a broker: Celery adds
scheduling, not behaviour, and running it inline lets each test assert on the
ledger and the event stream in the same transaction.
"""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.credits import service as credits_service
from app.domain.errors import CreditsExceedBudget, InsufficientCredits
from app.domain.jobs import service as jobs_service
from app.domain.jobs import state_machine as sm
from app.models import CreditLedgerEntry, GenerationJob, JobEvent, ProviderAttempt, User
from app.models.base import new_id, utcnow
from app.models.enums import JobStatus, LedgerEntryType, Operation, QualityTier
from app.providers.fake import FORCE_FAILURE_MARKER
from app.workers import pipeline, tasks


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


def test_a_stale_job_is_expired_and_its_credits_returned(db: Session, funded: User) -> None:
    """A worker that dies mid-flight would otherwise strand the reservation
    forever."""
    job = _submit(db, funded)
    job.created_at = utcnow() - tasks.STALE_JOB_TIMEOUT - dt.timedelta(minutes=1)
    db.flush()

    account = credits_service.get_or_create_account(db, funded.id)
    before = account.available_balance + job.reserved_credits

    jobs_service.settle_release(db, job, reason="expired")
    sm.transition(db, job.id, JobStatus.EXPIRED, failure_code="JOB_EXPIRED")

    db.refresh(job)
    db.refresh(account)
    assert job.status == JobStatus.EXPIRED
    assert account.reserved_balance == 0
    assert account.available_balance == before


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
    from app.platform_config import service as config_service
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
        "PROVIDER_CATALOG",
        {
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
    config_service.set_value(
        db,
        "providers",
        {"providers": {"slow_video": {"enabled": True}}},
        actor_user_id=None,
        note="test bootstrap",
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


def test_every_queue_named_in_the_routes_actually_exists() -> None:
    """A typo here would silently send tasks to a queue nobody consumes."""
    from app.workers.celery_app import QUEUE_NAMES, celery_app

    routed = {route["queue"] for route in celery_app.conf.task_routes.values()}
    assert routed <= set(QUEUE_NAMES)
    assert celery_app.conf.task_default_queue in QUEUE_NAMES
