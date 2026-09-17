"""`POST /v1/drafts/{id}/keyframe-confirmation`: the author's explicit OK on
one storyboard keyframe version as its segment's video first frame."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Asset, GenerationJob, User
from app.models.base import new_id
from app.models.enums import (
    AssetRole,
    JobStatus,
    MediaType,
    ModerationStatus,
    Operation,
    Visibility,
)
from tests.conftest import auth_header, make_user
from tests.factories import make_job


def _draft(client: TestClient, user: User, params: dict[str, Any]) -> str:
    response = client.post(
        "/v1/drafts",
        headers=auth_header(user),
        json={"source_work_id": None, "title": "日·客厅", "params": params},
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def _succeeded_version(db: Session, user: User, draft_id: str) -> GenerationJob:
    asset = Asset(
        owner_user_id=user.id,
        object_key=f"test/{new_id('obj')}.png",
        media_type=MediaType.IMAGE,
        mime_type="image/png",
        size_bytes=1024,
        checksum_sha256="e" * 64,
        role=AssetRole.GENERATION_OUTPUT,
        width=1080,
        height=1920,
        moderation_status=ModerationStatus.APPROVED,
        visibility=Visibility.PRIVATE,
    )
    db.add(asset)
    db.flush()
    job = make_job(db, user, status=JobStatus.SUCCEEDED, operation=Operation.TEXT_TO_IMAGE)
    job.draft_id = draft_id
    job.output_asset_id = asset.id
    db.flush()
    return job


KEYFRAME = {"operation": "text_to_image", "link_breakpoint_key": "日·客厅#K0", "prompt": "p"}


def test_confirming_pins_the_version_and_withdrawing_clears_it(
    client: TestClient, db: Session, author: User
) -> None:
    draft_id = _draft(client, author, KEYFRAME)
    job = _succeeded_version(db, author, draft_id)

    confirmed = client.post(
        f"/v1/drafts/{draft_id}/keyframe-confirmation",
        headers=auth_header(author),
        json={"job_id": job.id},
    )
    assert confirmed.status_code == 200, confirmed.text
    body = confirmed.json()
    assert body["params"]["keyframe_confirmed_job_id"] == job.id
    assert body["applied_job_id"] == job.id
    assert body["output_asset_id"] == job.output_asset_id

    withdrawn = client.post(
        f"/v1/drafts/{draft_id}/keyframe-confirmation",
        headers=auth_header(author),
        json={"job_id": None},
    )
    assert withdrawn.status_code == 200, withdrawn.text
    assert "keyframe_confirmed_job_id" not in withdrawn.json()["params"]


def test_only_a_keyframe_draft_can_be_confirmed(
    client: TestClient, db: Session, author: User
) -> None:
    draft_id = _draft(
        client, author, {"operation": "text_to_video", "link_breakpoint_key": "日·客厅#0"}
    )
    job = _succeeded_version(db, author, draft_id)

    response = client.post(
        f"/v1/drafts/{draft_id}/keyframe-confirmation",
        headers=auth_header(author),
        json={"job_id": job.id},
    )
    assert response.status_code == 422, response.text


def test_someone_elses_keyframe_cannot_be_confirmed(
    client: TestClient, db: Session, author: User
) -> None:
    draft_id = _draft(client, author, KEYFRAME)
    job = _succeeded_version(db, author, draft_id)
    stranger = make_user(db, email="kf-stranger@example.com", handle="kfstranger")

    response = client.post(
        f"/v1/drafts/{draft_id}/keyframe-confirmation",
        headers=auth_header(stranger),
        json={"job_id": job.id},
    )
    assert response.status_code in {403, 404}, response.text
