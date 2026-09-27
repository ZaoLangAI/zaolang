"""Character library CRUD (`/v1/characters`) — mirrors scene library
coverage (`test_scenes.py`), plus the reference-asset and publish/withdraw
endpoints a character skill (`CreationSkillCategory.CHARACTER`) has on top.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Asset, User
from app.models.base import new_id
from app.models.enums import (
    AssetRole,
    CharacterViewAngle,
    MediaType,
    ModerationStatus,
    Visibility,
)
from tests.conftest import auth_header


def _asset(session: Session, owner: User, *, media_type: MediaType = MediaType.IMAGE) -> Asset:
    asset = Asset(
        owner_user_id=owner.id,
        object_key=f"test/{new_id('obj')}.bin",
        media_type=media_type,
        mime_type="image/jpeg" if media_type == MediaType.IMAGE else "video/mp4",
        size_bytes=1024,
        checksum_sha256="d" * 64,
        role=AssetRole.GENERATION_OUTPUT,
        moderation_status=ModerationStatus.APPROVED,
        visibility=Visibility.PRIVATE,
    )
    session.add(asset)
    session.flush()
    return asset


def test_create_character_accepts_image_and_video_references(
    client: TestClient, db: Session, author: User
) -> None:
    image = _asset(db, author, media_type=MediaType.IMAGE)
    video = _asset(db, author, media_type=MediaType.VIDEO)

    response = client.post(
        "/v1/characters",
        json={
            "name": "林夏",
            "description": "外冷内热的便利店店员",
            "voice_description": "低沉、克制",
            "reference_asset_ids": [image.id, video.id],
        },
        headers=auth_header(author),
    )
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "林夏"
    assert body["status"] == "draft"
    assert body["visibility"] == "private"
    assert {entry["asset_id"] for entry in body["reference_assets"]} == {image.id, video.id}
    assert all(entry["url"] for entry in body["reference_assets"])


def test_create_character_rejects_audio_references(
    client: TestClient, db: Session, author: User
) -> None:
    audio = _asset(db, author, media_type=MediaType.AUDIO)
    response = client.post(
        "/v1/characters",
        json={"name": "配音角色", "reference_asset_ids": [audio.id]},
        headers=auth_header(author),
    )
    assert response.status_code == 422


def test_create_character_rejects_more_than_four_references(
    client: TestClient, db: Session, author: User
) -> None:
    assets = [_asset(db, author) for _ in range(5)]
    response = client.post(
        "/v1/characters",
        json={"name": "太多素材", "reference_asset_ids": [a.id for a in assets]},
        headers=auth_header(author),
    )
    assert response.status_code == 422


def test_list_get_update_delete_character_round_trip(
    client: TestClient, db: Session, author: User
) -> None:
    created = client.post(
        "/v1/characters", json={"name": "林夏"}, headers=auth_header(author)
    ).json()

    listed = client.get("/v1/characters", headers=auth_header(author))
    assert [c["id"] for c in listed.json()] == [created["id"]]

    fetched = client.get(f"/v1/characters/{created['id']}", headers=auth_header(author))
    assert fetched.status_code == 200
    assert fetched.json()["name"] == "林夏"

    updated = client.patch(
        f"/v1/characters/{created['id']}",
        json={"name": "林夏（改）", "description": "新设定"},
        headers=auth_header(author),
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "林夏（改）"
    assert updated.json()["description"] == "新设定"

    deleted = client.delete(f"/v1/characters/{created['id']}", headers=auth_header(author))
    assert deleted.status_code == 204
    assert (
        client.get(f"/v1/characters/{created['id']}", headers=auth_header(author)).status_code
        == 404
    )


def test_create_character_rejects_a_duplicate_name_for_the_same_owner(
    client: TestClient, db: Session, author: User
) -> None:
    first = client.post("/v1/characters", json={"name": "林彻"}, headers=auth_header(author))
    assert first.status_code == 201
    duplicate = client.post("/v1/characters", json={"name": " 林彻 "}, headers=auth_header(author))
    assert duplicate.status_code == 422
    body = duplicate.json()["error"]
    assert body["code"] == "VALIDATION_FAILED"
    assert body["details"]["fields"]["name"] == "角色名称已存在"


def test_update_character_rejects_renaming_onto_another_characters_name(
    client: TestClient, db: Session, author: User
) -> None:
    client.post("/v1/characters", json={"name": "林彻"}, headers=auth_header(author))
    other = client.post(
        "/v1/characters", json={"name": "母亲模仿者"}, headers=auth_header(author)
    ).json()
    response = client.patch(
        f"/v1/characters/{other['id']}",
        json={"name": "林彻"},
        headers=auth_header(author),
    )
    assert response.status_code == 422
    assert response.json()["error"]["details"]["fields"]["name"] == "角色名称已存在"


def test_two_owners_may_share_a_character_name(
    client: TestClient, db: Session, author: User, remixer: User
) -> None:
    mine = client.post("/v1/characters", json={"name": "林彻"}, headers=auth_header(author))
    theirs = client.post("/v1/characters", json={"name": "林彻"}, headers=auth_header(remixer))
    assert mine.status_code == 201
    assert theirs.status_code == 201
    assert mine.json()["id"] != theirs.json()["id"]


def test_character_is_scoped_to_its_owner(
    client: TestClient, db: Session, author: User, remixer: User
) -> None:
    created = client.post(
        "/v1/characters", json={"name": "别人的角色"}, headers=auth_header(author)
    ).json()

    response = client.get(f"/v1/characters/{created['id']}", headers=auth_header(remixer))
    assert response.status_code == 404


def test_reference_asset_update_and_delete_endpoints_persist_across_requests(
    client: TestClient, db: Session, author: User
) -> None:
    """Each request runs through its own dependency-injected session — this
    is the integration-level guard for the JSON-column dirty-tracking bug
    `test_characters_service.py` covers at the unit level: a follow-up `GET`
    in a *separate* request only sees the edit if the `PATCH` truly wrote it
    to the database, not just to an in-memory object that happened to survive
    within one request.
    """
    image = _asset(db, author, media_type=MediaType.IMAGE)
    created = client.post(
        "/v1/characters",
        json={"name": "神秘女侦探", "reference_asset_ids": [image.id]},
        headers=auth_header(author),
    ).json()

    patched = client.patch(
        f"/v1/characters/{created['id']}/reference-assets/{image.id}",
        json={"view": CharacterViewAngle.FRONT.value, "label": "正面"},
        headers=auth_header(author),
    )
    assert patched.status_code == 200
    assert patched.json()["reference_assets"][0]["view"] == CharacterViewAngle.FRONT.value

    refetched = client.get(f"/v1/characters/{created['id']}", headers=auth_header(author))
    entry = refetched.json()["reference_assets"][0]
    assert entry["view"] == CharacterViewAngle.FRONT.value
    assert entry["label"] == "正面"

    deleted = client.delete(
        f"/v1/characters/{created['id']}/reference-assets/{image.id}", headers=auth_header(author)
    )
    assert deleted.status_code == 200
    assert deleted.json()["reference_assets"] == []

    refetched_again = client.get(f"/v1/characters/{created['id']}", headers=auth_header(author))
    assert refetched_again.json()["reference_assets"] == []


def test_publish_requires_portrait_consent(client: TestClient, db: Session, author: User) -> None:
    created = client.post(
        "/v1/characters", json={"name": "角色"}, headers=auth_header(author)
    ).json()

    refused = client.post(
        f"/v1/characters/{created['id']}/publish",
        json={"portrait_consent": False},
        headers=auth_header(author),
    )
    assert refused.status_code == 422

    published = client.post(
        f"/v1/characters/{created['id']}/publish",
        json={"portrait_consent": True},
        headers=auth_header(author),
    )
    assert published.status_code == 200
    assert published.json()["status"] == "pending_review"
    assert published.json()["visibility"] == "public"


def test_withdraw_returns_a_published_character_to_draft(
    client: TestClient, db: Session, author: User
) -> None:
    created = client.post(
        "/v1/characters", json={"name": "角色"}, headers=auth_header(author)
    ).json()
    client.post(
        f"/v1/characters/{created['id']}/publish",
        json={"portrait_consent": True},
        headers=auth_header(author),
    )

    withdrawn = client.post(f"/v1/characters/{created['id']}/withdraw", headers=auth_header(author))
    assert withdrawn.status_code == 200
    assert withdrawn.json()["status"] == "draft"
    assert withdrawn.json()["visibility"] == "private"


def test_character_name_is_bounded_by_the_skill_title_column(
    client: TestClient, db: Session, author: User
) -> None:
    # A character is stored as a `CreationSkill` whose `title` is
    # `VARCHAR(80)` — a longer name must fail validation, not the INSERT.
    too_long = client.post("/v1/characters", json={"name": "角" * 81}, headers=auth_header(author))
    assert too_long.status_code == 422, too_long.text

    created = client.post("/v1/characters", json={"name": "角" * 80}, headers=auth_header(author))
    assert created.status_code == 201, created.text

    renamed = client.patch(
        f"/v1/characters/{created.json()['id']}",
        json={"name": "色" * 81},
        headers=auth_header(author),
    )
    assert renamed.status_code == 422, renamed.text
