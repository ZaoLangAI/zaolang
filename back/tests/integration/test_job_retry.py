"""`POST /v1/generation-jobs/{id}/retry`: resubmit a failed job as a new one.

A new job keeps the ledger honest (the first attempt's release and the
retry's reserve stay separate). The image studio resumes a draft via
`Draft.latest_job_id` only, so retry must advance that pointer the same
way create and promote already do — otherwise a queued/succeeded
notification click reopens the first failed attempt.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents import router as router_module
from app.domain.credits import service as credits_service
from app.domain.jobs import service as jobs_service
from app.domain.jobs import state_machine as sm
from app.models import Draft, GenerationJob, JobEvent, ProviderAttempt, User
from app.models.base import new_id
from app.models.enums import (
    JobEventType,
    JobStatus,
    Operation,
    ProviderAttemptStatus,
    QualityTier,
)
from app.providers.base import GenerationResult
from app.workers import pipeline
from tests import fake_providers
from tests.conftest import auth_header
from tests.fake_provider_catalog import build_fake_catalog

pytestmark = pytest.mark.usefixtures("fake_media_catalog")


def _failed_image_job(db: Session, author: User, *, draft_id: str) -> GenerationJob:
    credits_service.grant(db, author.id, 5_000, idempotency_key=new_id("grant"))
    result = jobs_service.submit(
        db,
        user_id=author.id,
        operation=Operation.TEXT_TO_IMAGE,
        quality_tier=QualityTier.STANDARD,
        params={"prompt": "雨后的东京街头", "aspect_ratio": "16:9"},
        idempotency_key=new_id("idk"),
        draft_id=draft_id,
    )
    jobs_service.settle_release(db, result.job, reason="test fail")
    failed = sm.transition(db, result.job.id, JobStatus.FAILED, failure_code="PROVIDER_ERROR")
    db.commit()
    return failed


def test_retrying_a_failed_job_points_the_draft_at_the_new_job(
    client: TestClient, db: Session, author: User
) -> None:
    draft = Draft(user_id=author.id, title="草稿")
    db.add(draft)
    db.flush()
    original = _failed_image_job(db, author, draft_id=draft.id)

    db.refresh(draft)
    assert draft.latest_job_id == original.id

    response = client.post(
        f"/v1/generation-jobs/{original.id}/retry",
        headers=auth_header(author),
    )

    assert response.status_code == 202, response.text
    body = response.json()
    assert body["id"] != original.id
    assert body["draft_id"] == draft.id
    assert body["status"] == JobStatus.CREATED

    retried = db.get(GenerationJob, body["id"])
    assert retried is not None
    assert retried.retry_of_job_id == original.id

    db.refresh(draft)
    assert draft.latest_job_id == body["id"]

    pipeline.run_generation_pipeline(db, body["id"])
    db.refresh(retried)
    assert retried.status == JobStatus.SUCCEEDED

    db.refresh(draft)
    assert draft.latest_job_id == body["id"]


def test_a_running_job_cannot_be_retried(client: TestClient, db: Session, author: User) -> None:
    credits_service.grant(db, author.id, 5_000, idempotency_key=new_id("grant"))
    result = jobs_service.submit(
        db,
        user_id=author.id,
        operation=Operation.TEXT_TO_IMAGE,
        quality_tier=QualityTier.STANDARD,
        params={"prompt": "雨后的东京街头", "aspect_ratio": "16:9"},
        idempotency_key=new_id("idk"),
    )
    db.commit()

    response = client.post(
        f"/v1/generation-jobs/{result.job.id}/retry",
        headers=auth_header(author),
    )

    assert response.status_code == 422


def test_retrying_someone_elses_job_is_not_found(
    client: TestClient, db: Session, author: User, remixer: User
) -> None:
    draft = Draft(user_id=author.id, title="草稿")
    db.add(draft)
    db.flush()
    original = _failed_image_job(db, author, draft_id=draft.id)

    response = client.post(
        f"/v1/generation-jobs/{original.id}/retry",
        headers=auth_header(remixer),
    )

    assert response.status_code == 404


def _always_fails(self: object, request: object) -> GenerationResult:
    del self, request
    return GenerationResult(
        succeeded=False, failure_code="PROVIDER_TEMPORARY_FAILURE", latency_ms=1, metadata={}
    )


def _event_types(db: Session, job_id: str) -> list[str]:
    rows = db.scalars(
        select(JobEvent.event_type).where(JobEvent.job_id == job_id).order_by(JobEvent.sequence)
    )
    return list(rows)


def test_retry_after_a_real_provider_failure_skips_pre_checks_and_excludes_it(
    client: TestClient, db: Session, author: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The end-to-end wiring: a job that genuinely exhausted its only tried
    candidate, then retried once that candidate is excluded and a second one
    is available, must skip straight to `route_score` and succeed on the
    other provider — without ever re-running `safety`/`planning`/
    `intent_router` for the new job.
    """
    monkeypatch.setattr(fake_providers.FakeOpenWorkflowProvider, "submit", _always_fails)
    full_catalog = build_fake_catalog()
    single_candidate = {"fake_open_workflow": full_catalog["fake_open_workflow"]}

    # The original run only ever has `fake_open_workflow` to try — a single
    # genuine failure is exactly a "no other candidate was ever tried" dead
    # end, not a "no candidate available at all" one.
    monkeypatch.setattr(router_module, "build_catalog", lambda session: single_candidate)
    credits_service.grant(db, author.id, 5_000, idempotency_key=new_id("grant"))
    result = jobs_service.submit(
        db,
        user_id=author.id,
        operation=Operation.TEXT_TO_IMAGE,
        quality_tier=QualityTier.STANDARD,
        params={"prompt": "雨后的东京街头", "aspect_ratio": "16:9"},
        idempotency_key=new_id("idk"),
    )
    db.commit()
    original = result.job

    pipeline.run_generation_pipeline(db, original.id)
    db.refresh(original)
    assert original.status == JobStatus.FAILED
    assert original.failure_code == "PROVIDER_TEMPORARY_FAILURE"

    attempts = list(
        db.scalars(select(ProviderAttempt).where(ProviderAttempt.job_id == original.id))
    )
    assert [a.provider for a in attempts] == ["fake_open_workflow"]
    assert attempts[0].status == ProviderAttemptStatus.FAILED.value

    # Both candidates are back in play for the retry — `fake_open_workflow`
    # must now be hard-excluded rather than picked again.
    monkeypatch.setattr(router_module, "build_catalog", lambda session: full_catalog)

    response = client.post(f"/v1/generation-jobs/{original.id}/retry", headers=auth_header(author))
    assert response.status_code == 202, response.text
    retried_id = response.json()["id"]

    pipeline.run_generation_pipeline(db, retried_id)
    retried = db.get(GenerationJob, retried_id)
    assert retried is not None
    assert retried.status == JobStatus.SUCCEEDED

    event_types = _event_types(db, retried_id)
    assert JobEventType.SAFETY.value not in event_types
    assert JobEventType.PLANNING.value not in event_types
    assert JobEventType.INTENT_ROUTING.value not in event_types
    # `jobs_service.submit()` always writes the leading "queued" event
    # itself, before the graph ever starts walking — `route_score` is the
    # very next thing, with nothing from a skipped pre-check node in between.
    assert event_types[0] == JobEventType.QUEUED.value
    assert event_types[1] == JobEventType.ROUTING.value

    excluded = next(c for c in retried.routing_trace_json if c["provider"] == "fake_open_workflow")
    assert excluded["eligible"] is False
    assert excluded["filter_reason"] == "previously_failed_this_job"
    assert retried.selected_route_summary_json["provider"] == "fake_paid_api"


def test_retry_with_forced_model_stays_failed_once_its_only_candidate_is_excluded(
    client: TestClient, db: Session, author: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`GenerationParams.forced_model` and the fast-retry path
    (`app.domain.jobs.fast_retry`) are independent mechanisms that must
    still compose correctly: a forced-model job whose one matching
    candidate genuinely failed must stay failed on retry — even though a
    *different* model (`fake_paid_api`) is available — never silently
    switch away from the model the user explicitly picked.
    """
    monkeypatch.setattr(fake_providers.FakeOpenWorkflowProvider, "submit", _always_fails)
    full_catalog = build_fake_catalog()
    single_candidate = {"fake_open_workflow": full_catalog["fake_open_workflow"]}
    monkeypatch.setattr(router_module, "build_catalog", lambda session: single_candidate)

    credits_service.grant(db, author.id, 5_000, idempotency_key=new_id("grant"))
    result = jobs_service.submit(
        db,
        user_id=author.id,
        operation=Operation.TEXT_TO_IMAGE,
        quality_tier=QualityTier.STANDARD,
        params={
            "prompt": "雨后的东京街头",
            "aspect_ratio": "16:9",
            "forced_model": "comfy-sdxl-base@1.4.0",
        },
        idempotency_key=new_id("idk"),
    )
    db.commit()
    original = result.job

    pipeline.run_generation_pipeline(db, original.id)
    db.refresh(original)
    assert original.status == JobStatus.FAILED
    assert original.failure_code == "PROVIDER_TEMPORARY_FAILURE"

    # The full catalog is back — `fake_paid_api` is a real, otherwise-
    # eligible candidate now, but it doesn't carry the forced model.
    monkeypatch.setattr(router_module, "build_catalog", lambda session: full_catalog)

    response = client.post(f"/v1/generation-jobs/{original.id}/retry", headers=auth_header(author))
    assert response.status_code == 202, response.text
    retried_id = response.json()["id"]

    pipeline.run_generation_pipeline(db, retried_id)
    retried = db.get(GenerationJob, retried_id)
    assert retried is not None
    assert retried.status == JobStatus.FAILED
    assert retried.failure_code == "PROVIDER_TEMPORARY_FAILURE"

    # Still took the fast-retry path (skipped straight to `route_score`).
    event_types = _event_types(db, retried_id)
    assert JobEventType.SAFETY.value not in event_types
    assert JobEventType.PLANNING.value not in event_types
    assert JobEventType.INTENT_ROUTING.value not in event_types

    excluded = next(c for c in retried.routing_trace_json if c["provider"] == "fake_open_workflow")
    assert excluded["eligible"] is False
    assert excluded["filter_reason"] == "previously_failed_this_job"
    # `fake_paid_api` was never even considered as a *replacement* — the
    # forced-model filter runs against whatever survived hard filtering,
    # and `fake_paid_api`'s model never matches `forced_model` regardless.
    assert not retried.selected_route_summary_json
