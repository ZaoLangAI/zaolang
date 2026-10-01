"""Scene library CRUD (`/v1/scenes`) — mirrors character library coverage.

A scene's reference assets accept images *or* videos, unlike most other
reference-asset checks in the platform, which is the one rule worth testing
directly rather than assuming it from the character-library pattern.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.domain.scenes import service as scenes_service
from app.models import Asset, User
from app.models.base import new_id
from app.models.enums import AssetRole, MediaType, ModerationStatus, Visibility
from tests.conftest import auth_header


def _asset(session: Session, owner: User, *, media_type: MediaType = MediaType.IMAGE) -> Asset:
    asset = Asset(
        owner_user_id=owner.id,
        object_key=f"test/{new_id('obj')}.bin",
        media_type=media_type,
        mime_type="image/jpeg" if media_type == MediaType.IMAGE else "video/mp4",
        size_bytes=1024,
        checksum_sha256="c" * 64,
        role=AssetRole.GENERATION_OUTPUT,
        moderation_status=ModerationStatus.APPROVED,
        visibility=Visibility.PRIVATE,
    )
    session.add(asset)
    session.flush()
    return asset


def test_create_scene_accepts_image_and_video_references(
    client: TestClient, db: Session, author: User
) -> None:
    image = _asset(db, author, media_type=MediaType.IMAGE)
    video = _asset(db, author, media_type=MediaType.VIDEO)

    response = client.post(
        "/v1/scenes",
        json={
            "name": "深夜便利店",
            "description": "日光灯嗡嗡作响",
            "reference_asset_ids": [image.id, video.id],
        },
        headers=auth_header(author),
    )
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "深夜便利店"
    assert {entry["asset_id"] for entry in body["reference_assets"]} == {image.id, video.id}
    assert all(entry["url"] for entry in body["reference_assets"])


def test_create_scene_rejects_audio_references(
    client: TestClient, db: Session, author: User
) -> None:
    audio = _asset(db, author, media_type=MediaType.AUDIO)
    response = client.post(
        "/v1/scenes",
        json={"name": "配音素材", "reference_asset_ids": [audio.id]},
        headers=auth_header(author),
    )
    assert response.status_code == 422


def test_create_scene_rejects_more_than_the_reference_cap(
    client: TestClient, db: Session, author: User
) -> None:
    assets = [_asset(db, author) for _ in range(scenes_service.MAX_REFERENCE_ASSETS + 1)]
    response = client.post(
        "/v1/scenes",
        json={"name": "太多素材", "reference_asset_ids": [a.id for a in assets]},
        headers=auth_header(author),
    )
    assert response.status_code == 422


def test_list_get_update_delete_scene_round_trip(
    client: TestClient, db: Session, author: User
) -> None:
    created = client.post("/v1/scenes", json={"name": "便利店"}, headers=auth_header(author)).json()

    listed = client.get("/v1/scenes", headers=auth_header(author))
    assert [s["id"] for s in listed.json()] == [created["id"]]

    fetched = client.get(f"/v1/scenes/{created['id']}", headers=auth_header(author))
    assert fetched.status_code == 200
    assert fetched.json()["name"] == "便利店"

    updated = client.patch(
        f"/v1/scenes/{created['id']}",
        json={"name": "深夜便利店", "description": "新增描述"},
        headers=auth_header(author),
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "深夜便利店"
    assert updated.json()["description"] == "新增描述"

    deleted = client.delete(f"/v1/scenes/{created['id']}", headers=auth_header(author))
    assert deleted.status_code == 204
    assert client.get(f"/v1/scenes/{created['id']}", headers=auth_header(author)).status_code == 404


def test_scene_is_scoped_to_its_owner(
    client: TestClient, db: Session, author: User, remixer: User
) -> None:
    created = client.post(
        "/v1/scenes", json={"name": "别人的场景"}, headers=auth_header(author)
    ).json()

    response = client.get(f"/v1/scenes/{created['id']}", headers=auth_header(remixer))
    assert response.status_code == 404


def test_reference_asset_update_and_delete_endpoints_persist_across_requests(
    client: TestClient, db: Session, author: User
) -> None:
    """Each request runs through its own dependency-injected session — the
    integration-level guard for the JSON-column dirty-tracking bug
    `test_scenes_service.py` covers at the unit level (see
    `scenes.service._reference_assets`): a follow-up `GET` in a *separate*
    request only sees the edit if the `PATCH` truly wrote it to the
    database, not just to an in-memory object that happened to survive
    within one request."""
    image = _asset(db, author, media_type=MediaType.IMAGE)
    created = client.post(
        "/v1/scenes",
        json={"name": "便利店", "reference_asset_ids": [image.id]},
        headers=auth_header(author),
    ).json()

    patched = client.patch(
        f"/v1/scenes/{created['id']}/reference-assets/{image.id}",
        json={"view": "establishing", "label": "空镜"},
        headers=auth_header(author),
    )
    assert patched.status_code == 200
    assert patched.json()["reference_assets"][0]["view"] == "establishing"

    refetched = client.get(f"/v1/scenes/{created['id']}", headers=auth_header(author))
    entry = refetched.json()["reference_assets"][0]
    assert entry["view"] == "establishing"
    assert entry["label"] == "空镜"

    deleted = client.delete(
        f"/v1/scenes/{created['id']}/reference-assets/{image.id}", headers=auth_header(author)
    )
    assert deleted.status_code == 200
    assert deleted.json()["reference_assets"] == []

    refetched_again = client.get(f"/v1/scenes/{created['id']}", headers=auth_header(author))
    assert refetched_again.json()["reference_assets"] == []


def test_publish_and_withdraw_scene_round_trip(
    client: TestClient, db: Session, author: User
) -> None:
    """A scene needs no portrait-consent gate (unlike a character), so both
    `/publish` and `/withdraw` are plain, body-less actions — see
    `scenes.service.publish_scene`."""
    created = client.post("/v1/scenes", json={"name": "便利店"}, headers=auth_header(author)).json()
    assert created["status"] == "draft"
    assert created["visibility"] == "private"

    published = client.post(f"/v1/scenes/{created['id']}/publish", headers=auth_header(author))
    assert published.status_code == 200
    assert published.json()["status"] == "pending_review"
    assert published.json()["visibility"] == "public"

    withdrawn = client.post(f"/v1/scenes/{created['id']}/withdraw", headers=auth_header(author))
    assert withdrawn.status_code == 200
    assert withdrawn.json()["status"] == "draft"
    assert withdrawn.json()["visibility"] == "private"


def test_scene_pricing_uses_the_generic_skill_pricing_endpoint(
    client: TestClient, db: Session, author: User
) -> None:
    """A scene is a `CreationSkill` under the hood, so the generic
    `PATCH /v1/skills/{id}/pricing` already works on it with no scene-specific
    endpoint needed — see `app.domain.skill_library.service.update_pricing`."""
    created = client.post("/v1/scenes", json={"name": "便利店"}, headers=auth_header(author)).json()
    assert created["access_credits"] == 0

    priced = client.patch(
        f"/v1/skills/{created['id']}/pricing",
        json={"access_credits": 50},
        headers=auth_header(author),
    )
    assert priced.status_code == 200

    refetched = client.get(f"/v1/scenes/{created['id']}", headers=auth_header(author))
    assert refetched.json()["access_credits"] == 50


def test_scene_name_is_bounded_by_the_skill_title_column(
    client: TestClient, db: Session, author: User
) -> None:
    # A scene is stored as a `CreationSkill` whose `title` is `VARCHAR(80)` —
    # a longer name must fail validation, not the INSERT.
    too_long = client.post("/v1/scenes", json={"name": "景" * 81}, headers=auth_header(author))
    assert too_long.status_code == 422, too_long.text

    created = client.post("/v1/scenes", json={"name": "景" * 80}, headers=auth_header(author))
    assert created.status_code == 201, created.text

    renamed = client.patch(
        f"/v1/scenes/{created.json()['id']}",
        json={"name": "场" * 81},
        headers=auth_header(author),
    )
    assert renamed.status_code == 422, renamed.text
