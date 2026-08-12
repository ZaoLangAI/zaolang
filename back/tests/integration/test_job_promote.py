"""`POST /v1/generation-jobs/{id}/promote`: upgrading a succeeded preview-tier
job to a full deep-generation job.

Modeled on `retry_job`'s own reasoning — a new job keeps the ledger honest
rather than reopening the preview's own reservation — but the precondition is
the mirror image: retry needs a failed/cancelled/expired job, promote needs a
succeeded preview one.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.domain.credits import service as credits_service
from app.domain.jobs import service as jobs_service
from app.models import Draft, GenerationJob, User
from app.models.base import new_id
from app.models.enums import JobStatus, Operation, QualityTier
from app.workers import pipeline
from tests.conftest import auth_header

pytestmark = pytest.mark.usefixtures("fake_media_catalog")


def _succeeded_preview_job(
    db: Session, author: User, *, draft_id: str | None = None
) -> GenerationJob:
    credits_service.grant(db, author.id, 5_000, idempotency_key=new_id("grant"))
    result = jobs_service.submit(
        db,
        user_id=author.id,
        operation=Operation.TEXT_TO_IMAGE,
        quality_tier=QualityTier.PREVIEW,
        params={"prompt": "雨后的东京街头", "aspect_ratio": "16:9"},
        idempotency_key=new_id("idk"),
        draft_id=draft_id,
    )
    pipeline.run_generation_pipeline(db, result.job.id)
    db.refresh(result.job)
    assert result.job.status == JobStatus.SUCCEEDED
    return result.job


def test_promoting_a_succeeded_preview_creates_a_new_job_at_the_chosen_tier(
    client: TestClient, db: Session, author: User
) -> None:
    draft = Draft(user_id=author.id, title="草稿")
    db.add(draft)
    db.flush()
    preview = _succeeded_preview_job(db, author, draft_id=draft.id)
    db.commit()

    response = client.post(
        f"/v1/generation-jobs/{preview.id}/promote",
        json={"quality_tier": "standard"},
        headers=auth_header(author),
    )

    assert response.status_code == 202, response.text
    body = response.json()
    assert body["id"] != preview.id
    assert body["quality_tier"] == "standard"
    assert body["promoted_from_job_id"] == preview.id
    assert body["draft_id"] == draft.id

    db.refresh(draft)
    assert draft.latest_job_id == body["id"]


def test_a_running_preview_cannot_be_promoted(
    client: TestClient, db: Session, author: User
) -> None:
    credits_service.grant(db, author.id, 5_000, idempotency_key=new_id("grant"))
    result = jobs_service.submit(
        db,
        user_id=author.id,
        operation=Operation.TEXT_TO_IMAGE,
        quality_tier=QualityTier.PREVIEW,
        params={"prompt": "雨后的东京街头", "aspect_ratio": "16:9"},
        idempotency_key=new_id("idk"),
    )
    db.commit()

    response = client.post(
        f"/v1/generation-jobs/{result.job.id}/promote",
        json={"quality_tier": "standard"},
        headers=auth_header(author),
    )

    assert response.status_code == 422


def test_a_succeeded_standard_tier_job_cannot_be_promoted(
    client: TestClient, db: Session, author: User
) -> None:
    """Only preview-tier successes are promotable — a standard job is already
    the real thing, not a draft to upgrade from."""
    credits_service.grant(db, author.id, 5_000, idempotency_key=new_id("grant"))
    result = jobs_service.submit(
        db,
        user_id=author.id,
        operation=Operation.TEXT_TO_IMAGE,
        quality_tier=QualityTier.STANDARD,
        params={"prompt": "雨后的东京街头", "aspect_ratio": "16:9"},
        idempotency_key=new_id("idk"),
    )
    pipeline.run_generation_pipeline(db, result.job.id)
    db.commit()

    response = client.post(
        f"/v1/generation-jobs/{result.job.id}/promote",
        json={"quality_tier": "cinematic"},
        headers=auth_header(author),
    )

    assert response.status_code == 422


def test_promoting_to_preview_again_is_refused(
    client: TestClient, db: Session, author: User
) -> None:
    preview = _succeeded_preview_job(db, author)
    db.commit()

    response = client.post(
        f"/v1/generation-jobs/{preview.id}/promote",
        json={"quality_tier": "preview"},
        headers=auth_header(author),
    )

    assert response.status_code == 422


def test_promoting_someone_elses_job_is_not_found(
    client: TestClient, db: Session, author: User, remixer: User
) -> None:
    preview = _succeeded_preview_job(db, author)
    db.commit()

    response = client.post(
        f"/v1/generation-jobs/{preview.id}/promote",
        json={"quality_tier": "standard"},
        headers=auth_header(remixer),
    )

    assert response.status_code == 404


def test_promoting_requires_a_session(client: TestClient, db: Session, author: User) -> None:
    preview = _succeeded_preview_job(db, author)
    db.commit()

    response = client.post(
        f"/v1/generation-jobs/{preview.id}/promote",
        json={"quality_tier": "standard"},
    )

    assert response.status_code == 401


def test_promoting_with_insufficient_credits_is_refused(
    client: TestClient, db: Session, author: User
) -> None:
    # `text_to_image` costs 4 credits at preview, 12 at standard (default
    # pricing) — funded for exactly the preview, nothing left to promote with.
    credits_service.grant(db, author.id, 4, idempotency_key=new_id("grant"))
    result = jobs_service.submit(
        db,
        user_id=author.id,
        operation=Operation.TEXT_TO_IMAGE,
        quality_tier=QualityTier.PREVIEW,
        params={"prompt": "雨后的东京街头", "aspect_ratio": "16:9"},
        idempotency_key=new_id("idk"),
    )
    pipeline.run_generation_pipeline(db, result.job.id)
    db.refresh(result.job)
    assert result.job.status == JobStatus.SUCCEEDED
    db.commit()

    response = client.post(
        f"/v1/generation-jobs/{result.job.id}/promote",
        json={"quality_tier": "standard"},
        headers=auth_header(author),
    )

    assert response.status_code == 402


def test_repeating_the_same_idempotency_key_replays_the_same_promotion(
    client: TestClient, db: Session, author: User
) -> None:
    preview = _succeeded_preview_job(db, author)
    db.commit()
    headers = {**auth_header(author), "Idempotency-Key": new_id("idk")}

    first = client.post(
        f"/v1/generation-jobs/{preview.id}/promote",
        json={"quality_tier": "standard"},
        headers=headers,
    )
    second = client.post(
        f"/v1/generation-jobs/{preview.id}/promote",
        json={"quality_tier": "standard"},
        headers=headers,
    )

    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["id"] == second.json()["id"]
