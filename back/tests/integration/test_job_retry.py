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
from sqlalchemy.orm import Session

from app.domain.credits import service as credits_service
from app.domain.jobs import service as jobs_service
from app.domain.jobs import state_machine as sm
from app.models import Draft, GenerationJob, User
from app.models.base import new_id
from app.models.enums import JobStatus, Operation, QualityTier
from app.workers import pipeline
from tests.conftest import auth_header

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
    failed = sm.transition(
        db, result.job.id, JobStatus.FAILED, failure_code="PROVIDER_ERROR"
    )
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


def test_a_running_job_cannot_be_retried(
    client: TestClient, db: Session, author: User
) -> None:
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
