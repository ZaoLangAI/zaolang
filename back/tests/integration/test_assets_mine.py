"""`GET /v1/assets:mine` — the editor's media-library listing."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Asset, User
from app.models.base import new_id
from app.models.enums import AssetRole, MediaType, ModerationStatus, Visibility
from tests.conftest import auth_header


def _asset(
    session: Session,
    owner: User,
    *,
    media_type: MediaType = MediaType.VIDEO,
    role: AssetRole = AssetRole.GENERATION_OUTPUT,
    moderation_status: ModerationStatus = ModerationStatus.APPROVED,
) -> Asset:
    asset = Asset(
        owner_user_id=owner.id,
        object_key=f"test/{new_id('obj')}.bin",
        media_type=media_type,
        mime_type={"video": "video/mp4", "audio": "audio/mpeg", "image": "image/png"}[
            media_type.value
        ],
        size_bytes=2048,
        checksum_sha256="c" * 64,
        role=role,
        duration_ms=5_000 if media_type != MediaType.IMAGE else None,
        moderation_status=moderation_status,
        visibility=Visibility.PRIVATE,
    )
    session.add(asset)
    session.flush()
    return asset


def test_lists_only_the_callers_own_source_material(
    client: TestClient, db: Session, author: User, remixer: User
) -> None:
    mine_video = _asset(db, author, media_type=MediaType.VIDEO)
    mine_upload = _asset(db, author, media_type=MediaType.AUDIO, role=AssetRole.EDITOR_SOURCE)
    _asset(db, remixer, media_type=MediaType.VIDEO)  # someone else's — must not appear
    _asset(db, author, role=AssetRole.AVATAR)  # not source material — must not appear
    _asset(db, author, moderation_status=ModerationStatus.REJECTED)  # rejected — must not appear
    db.commit()

    response = client.get("/v1/assets:mine", headers=auth_header(author))
    assert response.status_code == 200, response.text
    ids = {item["id"] for item in response.json()["items"]}
    assert ids == {mine_video.id, mine_upload.id}


def test_media_type_filter(client: TestClient, db: Session, author: User) -> None:
    video = _asset(db, author, media_type=MediaType.VIDEO)
    _asset(db, author, media_type=MediaType.AUDIO)
    db.commit()

    response = client.get(
        "/v1/assets:mine", headers=auth_header(author), params={"media_type": "video"}
    )
    assert response.status_code == 200, response.text
    ids = {item["id"] for item in response.json()["items"]}
    assert ids == {video.id}


def test_requires_authentication(client: TestClient) -> None:
    response = client.get("/v1/assets:mine")
    assert response.status_code == 401
