"""Draft list/detail projections, including output media metadata."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.domain.publishing import service as publishing
from app.models import Asset, User
from app.models.base import new_id
from app.models.enums import AssetRole, MediaType, ModerationStatus, Visibility
from tests.conftest import auth_header


@pytest.mark.parametrize(
    ("media_type", "mime_type", "duration_ms"),
    [
        (MediaType.IMAGE, "image/png", None),
        (MediaType.VIDEO, "video/mp4", 8_000),
    ],
)
def test_draft_response_exposes_output_media_meta(
    client: TestClient,
    db: Session,
    author: User,
    media_type: MediaType,
    mime_type: str,
    duration_ms: int | None,
) -> None:
    asset = Asset(
        owner_user_id=author.id,
        object_key=f"test/{new_id('obj')}",
        media_type=media_type,
        mime_type=mime_type,
        size_bytes=128,
        checksum_sha256="b" * 64,
        role=AssetRole.GENERATION_OUTPUT,
        width=1920,
        height=1080,
        duration_ms=duration_ms,
        moderation_status=ModerationStatus.APPROVED,
        visibility=Visibility.PRIVATE,
    )
    db.add(asset)
    db.flush()
    draft = publishing.create_draft(db, user_id=author.id, source_work_id=None, title="雾谷")
    draft.output_asset_id = asset.id
    db.flush()

    response = client.get(f"/v1/drafts/{draft.id}", headers=auth_header(author))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["output_media_type"] == media_type.value
    assert body["output_asset_id"] == asset.id
    assert body["output_url"]
    assert body["width"] == 1920
    assert body["height"] == 1080
    assert body["duration_ms"] == duration_ms


def test_draft_without_output_omits_media_meta(
    client: TestClient, db: Session, author: User
) -> None:
    draft = publishing.create_draft(db, user_id=author.id, source_work_id=None)

    response = client.get(f"/v1/drafts/{draft.id}", headers=auth_header(author))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["output_asset_id"] is None
    assert body["output_url"] is None
    assert body["output_media_type"] is None
    assert body["duration_ms"] is None
    assert body["width"] is None
    assert body["height"] is None
