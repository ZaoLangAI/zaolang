"""`GET /v1/assets:mine` — the editor's media-library listing."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Asset, User
from app.models.base import new_id
from app.models.enums import (
    AssetRole,
    ImageAssetKind,
    JobStatus,
    MediaType,
    ModerationStatus,
    Visibility,
)
from tests.conftest import auth_header
from tests.factories import make_job


def _asset(
    session: Session,
    owner: User,
    *,
    media_type: MediaType = MediaType.VIDEO,
    role: AssetRole = AssetRole.GENERATION_OUTPUT,
    moderation_status: ModerationStatus = ModerationStatus.APPROVED,
    object_key: str | None = None,
) -> Asset:
    asset = Asset(
        owner_user_id=owner.id,
        object_key=object_key or f"test/{new_id('obj')}.bin",
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


def _link_job_output(
    session: Session,
    owner: User,
    asset: Asset,
    *,
    asset_kind: str,
    extra_output_ids: list[str] | None = None,
) -> None:
    job = make_job(session, owner)
    job.request_json = {**job.request_json, "asset_kind": asset_kind}
    job.output_asset_id = asset.id
    job.output_asset_ids_json = [asset.id, *(extra_output_ids or [])]


def test_hides_character_and_scene_outputs(client: TestClient, db: Session, author: User) -> None:
    general = _asset(db, author, media_type=MediaType.IMAGE)
    cover = _asset(db, author, media_type=MediaType.IMAGE)
    character = _asset(db, author, media_type=MediaType.IMAGE)
    character_side = _asset(db, author, media_type=MediaType.IMAGE)
    scene = _asset(db, author, media_type=MediaType.IMAGE)
    video = _asset(db, author, media_type=MediaType.VIDEO)
    upload = _asset(db, author, media_type=MediaType.IMAGE, role=AssetRole.EDITOR_SOURCE)

    _link_job_output(db, author, general, asset_kind=ImageAssetKind.GENERAL.value)
    _link_job_output(db, author, cover, asset_kind=ImageAssetKind.COVER.value)
    _link_job_output(
        db,
        author,
        character,
        asset_kind=ImageAssetKind.CHARACTER.value,
        extra_output_ids=[character_side.id],
    )
    _link_job_output(db, author, scene, asset_kind=ImageAssetKind.SCENE.value)
    _link_job_output(db, author, video, asset_kind="character_action")
    failed_job = make_job(db, author, status=JobStatus.FAILED)
    failed_job.request_json = {
        **failed_job.request_json,
        "asset_kind": ImageAssetKind.CHARACTER.value,
    }
    failed_partial = _asset(
        db,
        author,
        media_type=MediaType.IMAGE,
        object_key=f"generated/{failed_job.id}/output_1.png",
    )
    db.commit()

    response = client.get("/v1/assets:mine", headers=auth_header(author))
    assert response.status_code == 200, response.text
    ids = {item["id"] for item in response.json()["items"]}
    assert ids == {general.id, cover.id, video.id, upload.id}
    assert character.id not in ids
    assert character_side.id not in ids
    assert scene.id not in ids
    assert failed_partial.id not in ids
