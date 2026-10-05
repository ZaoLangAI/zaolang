"""P4: `GET /v1/{characters|scenes}/{id}/graph` and the edge writes."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import CreationSkill, User
from app.models.enums import CreationSkillStatus, CreationSkillVisibility
from tests.conftest import auth_header


def _character(client: TestClient, user: User, name: str = "林夏") -> dict:
    response = client.post(
        "/v1/characters",
        json={"name": name, "description": "完整的角色描述" * 60},
        headers=auth_header(user),
    )
    assert response.status_code == 201
    return response.json()


def _look(client: TestClient, user: User, card_id: str, name: str, **body) -> str:
    response = client.post(
        f"/v1/characters/{card_id}/looks", json={"name": name, **body}, headers=auth_header(user)
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_the_graph_returns_looks_edges_and_caps(
    client: TestClient, db: Session, author: User
) -> None:
    card = _character(client, author)
    headers = auth_header(author)
    young = _look(client, author, card["id"], "青年", presets={"age_stage": "youth"})
    old = _look(client, author, card["id"], "老年", presets={"age_stage": "elderly"})
    created = client.post(
        f"/v1/characters/{card['id']}/edges",
        json={"level": "variant", "source_id": young, "target_id": old, "relations": ["age"]},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    edge = created.json()
    assert edge["origin"] == "manual"

    body = client.get(f"/v1/characters/{card['id']}/graph", headers=headers).json()
    assert body["card_kind"] == "character"
    # The full description, not the 300-char preview.
    assert len(body["description"]) > 300
    assert [v["name"] for v in body["variants"]] == ["默认造型", "青年", "老年"]
    assert body["edges"] == [edge]
    assert body["pending"] == []
    assert body["caps"]["max_variants"] == 48
    assert body["caps"]["max_entries"] == 480


def test_a_cycle_is_a_422(client: TestClient, db: Session, author: User) -> None:
    card = _character(client, author)
    headers = auth_header(author)
    a = _look(client, author, card["id"], "甲")
    b = _look(client, author, card["id"], "乙")
    base = f"/v1/characters/{card['id']}/edges"
    client.post(
        base,
        json={"level": "variant", "source_id": a, "target_id": b, "relations": ["outfit"]},
        headers=headers,
    )
    back = client.post(
        base,
        json={"level": "variant", "source_id": b, "target_id": a, "relations": ["outfit"]},
        headers=headers,
    )
    assert back.status_code == 422
    assert back.json()["error"]["details"]["fields"]["target_id"] == "会形成环"


def test_edges_can_be_relabelled_and_deleted_without_withdrawing(
    client: TestClient, db: Session, author: User
) -> None:
    card = _character(client, author)
    headers = auth_header(author)
    a = _look(client, author, card["id"], "甲")
    b = _look(client, author, card["id"], "乙")
    edge = client.post(
        f"/v1/characters/{card['id']}/edges",
        json={"level": "variant", "source_id": a, "target_id": b, "relations": ["outfit"]},
        headers=headers,
    ).json()
    skill = db.get(CreationSkill, card["id"])
    assert skill is not None
    skill.status = CreationSkillStatus.PUBLISHED
    skill.visibility = CreationSkillVisibility.PUBLIC
    db.flush()

    patched = client.patch(
        f"/v1/characters/{card['id']}/edges/{edge['id']}",
        json={"relations": ["custom"], "label": "第二幕"},
        headers=headers,
    )
    assert patched.status_code == 200
    assert patched.json()["label"] == "第二幕"
    deleted = client.delete(f"/v1/characters/{card['id']}/edges/{edge['id']}", headers=headers)
    assert deleted.status_code == 204
    db.expire_all()
    # Graph metadata is not published content.
    assert db.get(CreationSkill, card["id"]).status == CreationSkillStatus.PUBLISHED  # type: ignore[union-attr]


def test_scene_graphs_share_the_routes(client: TestClient, db: Session, author: User) -> None:
    headers = auth_header(author)
    scene = client.post("/v1/scenes", json={"name": "码头"}, headers=headers).json()
    body = client.get(f"/v1/scenes/{scene['id']}/graph", headers=headers).json()
    assert body["card_kind"] == "scene"
    assert body["caps"]["max_variants"] is None


def test_the_graph_is_owner_only(
    client: TestClient, db: Session, author: User, remixer: User
) -> None:
    card = _character(client, author)
    a = _look(client, author, card["id"], "甲")
    b = _look(client, author, card["id"], "乙")
    edge = client.post(
        f"/v1/characters/{card['id']}/edges",
        json={"level": "variant", "source_id": a, "target_id": b, "relations": ["outfit"]},
        headers=auth_header(author),
    ).json()
    theirs = auth_header(remixer)
    assert client.get(f"/v1/characters/{card['id']}/graph", headers=theirs).status_code == 404
    assert (
        client.delete(f"/v1/characters/{card['id']}/edges/{edge['id']}", headers=theirs).status_code
        == 404
    )
    # Another card's edge id under my own card is a 404 too.
    mine = _character(client, remixer, name="周岩")
    assert (
        client.delete(f"/v1/characters/{mine['id']}/edges/{edge['id']}", headers=theirs).status_code
        == 404
    )
    assert client.get(f"/v1/characters/{card['id']}/graph").status_code == 401
