"""Draft applied-version pin and version-history hide."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.domain.publishing import service as publishing
from app.models import Asset, Draft, GenerationJob, User
from app.models.base import new_id
from app.models.enums import (
    AssetRole,
    JobStatus,
    MediaType,
    ModerationStatus,
    Operation,
    Visibility,
)
from tests.conftest import auth_header
from tests.factories import make_job


def _output_asset(db: Session, author: User) -> Asset:
    asset = Asset(
        owner_user_id=author.id,
        object_key=f"test/{new_id('obj')}",
        media_type=MediaType.VIDEO,
        mime_type="video/mp4",
        size_bytes=128,
        checksum_sha256="c" * 64,
        role=AssetRole.GENERATION_OUTPUT,
        width=1920,
        height=1080,
        duration_ms=8_000,
        moderation_status=ModerationStatus.APPROVED,
        visibility=Visibility.PRIVATE,
    )
    db.add(asset)
    db.flush()
    return asset


def _succeeded_job(
    db: Session,
    author: User,
    draft: Draft,
    *,
    prompt: str,
    asset: Asset,
) -> GenerationJob:
    job = make_job(db, author, status=JobStatus.SUCCEEDED, operation=Operation.TEXT_TO_VIDEO)
    job.draft_id = draft.id
    job.request_json = {"prompt": prompt, "duration_seconds": 8}
    job.output_asset_id = asset.id
    db.flush()
    return job


def test_apply_version_points_output_without_moving_latest_job(
    client: TestClient, db: Session, author: User
) -> None:
    draft = publishing.create_draft(db, user_id=author.id, source_work_id=None)
    older_asset = _output_asset(db, author)
    newer_asset = _output_asset(db, author)
    older = _succeeded_job(db, author, draft, prompt="旧版提示词", asset=older_asset)
    newer = _succeeded_job(db, author, draft, prompt="新版提示词", asset=newer_asset)
    draft.latest_job_id = newer.id
    draft.applied_job_id = newer.id
    draft.output_asset_id = newer_asset.id
    db.commit()

    response = client.post(
        f"/v1/drafts/{draft.id}/applied-version",
        headers=auth_header(author),
        json={"job_id": older.id},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["applied_job_id"] == older.id
    assert body["output_asset_id"] == older_asset.id
    assert body["latest_job_id"] == newer.id

    db.refresh(draft)
    assert draft.applied_job_id == older.id
    assert draft.output_asset_id == older_asset.id
    assert draft.latest_job_id == newer.id


def test_hide_applied_version_falls_back_to_previous_success(
    client: TestClient, db: Session, author: User
) -> None:
    draft = publishing.create_draft(db, user_id=author.id, source_work_id=None)
    older_asset = _output_asset(db, author)
    newer_asset = _output_asset(db, author)
    older = _succeeded_job(db, author, draft, prompt="旧", asset=older_asset)
    newer = _succeeded_job(db, author, draft, prompt="新", asset=newer_asset)
    draft.latest_job_id = newer.id
    draft.applied_job_id = newer.id
    draft.output_asset_id = newer_asset.id
    db.commit()

    hidden = client.delete(
        f"/v1/drafts/{draft.id}/versions/{newer.id}",
        headers=auth_header(author),
    )
    assert hidden.status_code == 204, hidden.text

    listed = client.get(
        f"/v1/generation-jobs?draft_id={draft.id}",
        headers=auth_header(author),
    )
    assert listed.status_code == 200
    ids = [item["id"] for item in listed.json()["items"]]
    assert newer.id not in ids
    assert older.id in ids

    db.refresh(draft)
    db.refresh(newer)
    assert newer.draft_history_hidden_at is not None
    assert draft.applied_job_id == older.id
    assert draft.output_asset_id == older_asset.id
    assert draft.latest_job_id == newer.id


def test_hide_last_visible_version_clears_applied_pointers(
    client: TestClient, db: Session, author: User
) -> None:
    draft = publishing.create_draft(db, user_id=author.id, source_work_id=None)
    asset = _output_asset(db, author)
    job = _succeeded_job(db, author, draft, prompt="唯一", asset=asset)
    draft.latest_job_id = job.id
    draft.applied_job_id = job.id
    draft.output_asset_id = asset.id
    db.commit()

    hidden = client.delete(
        f"/v1/drafts/{draft.id}/versions/{job.id}",
        headers=auth_header(author),
    )
    assert hidden.status_code == 204, hidden.text

    db.refresh(draft)
    assert draft.applied_job_id is None
    assert draft.output_asset_id is None


def test_cannot_hide_an_in_flight_version(client: TestClient, db: Session, author: User) -> None:
    draft = publishing.create_draft(db, user_id=author.id, source_work_id=None)
    job = make_job(db, author, status=JobStatus.RUNNING, operation=Operation.TEXT_TO_VIDEO)
    job.draft_id = draft.id
    db.commit()

    response = client.delete(
        f"/v1/drafts/{draft.id}/versions/{job.id}",
        headers=auth_header(author),
    )
    assert response.status_code == 422
    assert job.draft_history_hidden_at is None


def test_cannot_apply_a_hidden_or_unfinished_version(
    client: TestClient, db: Session, author: User
) -> None:
    draft = publishing.create_draft(db, user_id=author.id, source_work_id=None)
    running = make_job(db, author, status=JobStatus.RUNNING, operation=Operation.TEXT_TO_VIDEO)
    running.draft_id = draft.id
    asset = _output_asset(db, author)
    hidden = _succeeded_job(db, author, draft, prompt="隐藏", asset=asset)
    hidden.draft_history_hidden_at = hidden.created_at
    db.commit()

    unfinished = client.post(
        f"/v1/drafts/{draft.id}/applied-version",
        headers=auth_header(author),
        json={"job_id": running.id},
    )
    assert unfinished.status_code == 422

    tombstoned = client.post(
        f"/v1/drafts/{draft.id}/applied-version",
        headers=auth_header(author),
        json={"job_id": hidden.id},
    )
    assert tombstoned.status_code == 422


def test_draft_response_exposes_applied_job_id(
    client: TestClient, db: Session, author: User
) -> None:
    draft = publishing.create_draft(db, user_id=author.id, source_work_id=None)
    response = client.get(f"/v1/drafts/{draft.id}", headers=auth_header(author))
    assert response.status_code == 200
    assert response.json()["applied_job_id"] is None
