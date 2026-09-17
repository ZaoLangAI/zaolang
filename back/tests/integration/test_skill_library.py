"""C-end `/v1/skills` plaza: create, list public, and applicable operations."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.domain.characters import service as characters_service
from app.domain.scenes import service as scenes_service
from app.models import CreationSkill, User
from app.models.enums import CreationSkillStatus, Operation
from tests.conftest import auth_header


def _create_payload(**overrides: object) -> dict:
    payload: dict = {
        "title": "电影感夜景",
        "description": "低角度霓虹夜景，适合城市镜头。",
        "category": "lens",
        "params": {"prompt_suffix": "cinematic night scene, neon"},
    }
    payload.update(overrides)
    return payload


def test_anonymous_public_listing_returns_200(client: TestClient) -> None:
    response = client.get("/v1/skills/public")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["items"] == []
    assert body["has_more"] is False


def test_create_skill_stores_applicable_operations(client: TestClient, author: User) -> None:
    created = client.post(
        "/v1/skills",
        json=_create_payload(
            applicable_operations=[
                Operation.TEXT_TO_VIDEO.value,
                Operation.IMAGE_TO_VIDEO.value,
            ]
        ),
        headers=auth_header(author),
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["applicable_operations"] == [
        Operation.TEXT_TO_VIDEO.value,
        Operation.IMAGE_TO_VIDEO.value,
    ]
    assert body["status"] == CreationSkillStatus.DRAFT.value

    detail = client.get(f"/v1/skills/{body['id']}", headers=auth_header(author))
    assert detail.status_code == 200, detail.text
    assert detail.json()["applicable_operations"] == body["applicable_operations"]


def test_the_owner_can_delete_their_own_skill(
    client: TestClient, db: Session, author: User
) -> None:
    created = client.post("/v1/skills", json=_create_payload(), headers=auth_header(author))
    skill_id = created.json()["id"]

    response = client.delete(f"/v1/skills/{skill_id}", headers=auth_header(author))
    assert response.status_code == 204, response.text
    assert db.get(CreationSkill, skill_id) is None


def test_list_mine_excludes_image_asset_skills(
    client: TestClient, db: Session, author: User
) -> None:
    """The generic "我的技能" list (`GET /v1/skills`) is `ManageSkillDialog`
    territory, which cannot edit a character/scene's structured reference
    assets — those stay confined to their own maintenance pages."""
    template = client.post("/v1/skills", json=_create_payload(), headers=auth_header(author))
    template_id = template.json()["id"]

    scene = scenes_service.create_scene(
        db, user_id=author.id, name="深夜便利店", description=None, reference_asset_ids=[]
    )
    character = characters_service.create_character(
        db,
        user_id=author.id,
        name="林夏",
        description=None,
        reference_asset_ids=[],
        voice_description=None,
    )
    db.commit()

    mine = client.get("/v1/skills", headers=auth_header(author))
    assert mine.status_code == 200, mine.text
    ids = {item["id"] for item in mine.json()["items"]}
    assert ids == {template_id}
    assert scene.id not in ids
    assert character.id not in ids


def test_you_cannot_delete_someone_elses_skill(
    client: TestClient, db: Session, author: User, remixer: User
) -> None:
    created = client.post("/v1/skills", json=_create_payload(), headers=auth_header(author))
    skill_id = created.json()["id"]

    response = client.delete(f"/v1/skills/{skill_id}", headers=auth_header(remixer))
    assert response.status_code == 404, response.text
    assert db.get(CreationSkill, skill_id) is not None


def test_public_listing_only_shows_published_skills(
    client: TestClient, db: Session, author: User
) -> None:
    created = client.post("/v1/skills", json=_create_payload(), headers=auth_header(author))
    assert created.status_code == 201, created.text
    skill_id = created.json()["id"]
    assert created.json()["applicable_operations"] == []

    public_before = client.get("/v1/skills/public")
    assert public_before.status_code == 200, public_before.text
    assert not any(item["id"] == skill_id for item in public_before.json()["items"])

    skill = db.get(CreationSkill, skill_id)
    assert skill is not None
    skill.status = CreationSkillStatus.PUBLISHED
    db.commit()

    public_after = client.get("/v1/skills/public")
    assert public_after.status_code == 200, public_after.text
    listed = next(item for item in public_after.json()["items"] if item["id"] == skill_id)
    assert listed["title"] == "电影感夜景"
    assert listed["applicable_operations"] == []
    assert listed["cover_media_type"] is None


# ---- content_type filtering (template vs. image_asset) --------------------


def test_content_type_filter_separates_templates_from_image_assets(
    client: TestClient, db: Session, author: User
) -> None:
    template = client.post("/v1/skills", json=_create_payload(), headers=auth_header(author))
    template_id = template.json()["id"]
    db.get(CreationSkill, template_id).status = CreationSkillStatus.PUBLISHED

    scene = scenes_service.create_scene(
        db, user_id=author.id, name="深夜便利店", description=None, reference_asset_ids=[]
    )
    scenes_service.publish_scene(db, user_id=author.id, scene_id=scene.id)
    db.get(CreationSkill, scene.id).status = CreationSkillStatus.PUBLISHED
    db.commit()

    templates_only = client.get("/v1/skills/public", params={"content_type": "template"})
    assert templates_only.status_code == 200, templates_only.text
    ids = {item["id"] for item in templates_only.json()["items"]}
    assert template_id in ids
    assert scene.id not in ids

    image_assets_only = client.get("/v1/skills/public", params={"content_type": "image_asset"})
    assert image_assets_only.status_code == 200, image_assets_only.text
    ids = {item["id"] for item in image_assets_only.json()["items"]}
    assert scene.id in ids
    assert template_id not in ids


def test_default_public_listing_excludes_image_asset_skills(
    client: TestClient, db: Session, author: User
) -> None:
    scene = scenes_service.create_scene(
        db, user_id=author.id, name="深夜便利店", description=None, reference_asset_ids=[]
    )
    scenes_service.publish_scene(db, user_id=author.id, scene_id=scene.id)
    db.get(CreationSkill, scene.id).status = CreationSkillStatus.PUBLISHED
    db.commit()

    response = client.get("/v1/skills/public")
    assert response.status_code == 200, response.text
    assert not any(item["id"] == scene.id for item in response.json()["items"])


# ---- character publish must go through the dedicated endpoint -------------


def test_generic_publish_route_rejects_character_skills(
    client: TestClient, db: Session, author: User
) -> None:
    character = characters_service.create_character(
        db,
        user_id=author.id,
        name="林夏",
        description=None,
        reference_asset_ids=[],
        voice_description=None,
    )
    db.commit()

    response = client.post(f"/v1/skills/{character.id}/publish", headers=auth_header(author))
    assert response.status_code == 422, response.text
