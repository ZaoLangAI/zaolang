"""C-end `/v1/skills` plaza: create, list public, and applicable operations."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

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
