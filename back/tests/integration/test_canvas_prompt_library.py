"""Skill cards dropped on a canvas from the prompt library.

Two things are pinned here, and they are the two that make this different
from every other binding on the canvas:

* A node-bound skill hydrates in **both** modes. Before `binding_skill_id`
  existed, `domain_snapshot` only ever returned skills a *drama episode*
  referenced, so a skill card on a free canvas resolved to nothing and the
  client rendered it permanently stale — the card worked exactly once, before
  the first reload.
* The id on the card is **client-written**, unlike the episode-derived ids,
  so hydrating it without an access check would turn a canvas read into a
  peek at someone else's unpublished draft.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import CreationSkill, User
from app.models.enums import (
    CreationSkillCategory,
    CreationSkillStatus,
    CreationSkillVisibility,
)
from app.platform_config import service as config_service
from app.platform_config.schemas import FeatureFlags
from tests.conftest import auth_header, make_user


def _set_canvas_flag(session: Session, *, enabled: bool) -> None:
    value = config_service.get_typed(session, "feature_flags", FeatureFlags).model_dump(mode="json")
    value.update({"canvas_studio_enabled": enabled})
    config_service.set_value(session, "feature_flags", value, actor_user_id=None, note="test")


def _skill(
    session: Session,
    owner: User,
    *,
    title: str,
    status: CreationSkillStatus = CreationSkillStatus.PUBLISHED,
) -> CreationSkill:
    skill = CreationSkill(
        owner_user_id=owner.id,
        title=title,
        category=CreationSkillCategory.LENS,
        status=status,
        visibility=CreationSkillVisibility.PUBLIC,
        params_json={"prompt_suffix": "低角度广角"},
    )
    session.add(skill)
    session.flush()
    return skill


def _canvas(client: TestClient, user: User) -> str:
    response = client.post(
        "/v1/canvas-projects", json={"title": "灵感沙盒"}, headers=auth_header(user)
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _drop_skill_card(client: TestClient, user: User, canvas_id: str, skill_id: str):
    return client.post(
        f"/v1/canvas-projects/{canvas_id}/graph-ops",
        json={
            "base_seq": 0,
            "ops": [
                {
                    "op_id": "op_skill",
                    "kind": "node.create",
                    "node": {
                        "id": "cnd_libtest0000000000000000",
                        "kind": "skill",
                        "position": {"x": 10, "y": 20},
                        "binding": {"kind": "skill", "skill_id": skill_id},
                    },
                }
            ],
        },
        headers=auth_header(user),
    )


def test_a_skill_card_on_a_free_canvas_hydrates(
    client: TestClient, db: Session, author: User
) -> None:
    _set_canvas_flag(db, enabled=True)
    skill = _skill(db, author, title="低角度广角")
    canvas_id = _canvas(client, author)
    assert _drop_skill_card(client, author, canvas_id, skill.id).status_code == 200

    body = client.get(f"/v1/canvas-projects/{canvas_id}", headers=auth_header(author)).json()
    # A free canvas has no episodes at all, so this can only have come from the
    # node's own binding.
    assert [entry["id"] for entry in body["snapshot"]["skills"]] == [skill.id]
    assert body["snapshot"]["skills"][0]["title"] == "低角度广角"


def test_someone_elses_draft_skill_does_not_hydrate(
    client: TestClient, db: Session, author: User
) -> None:
    """The id is whatever the browser wrote into the card, so pasting a
    stranger's unpublished skill must not leak its title back."""
    _set_canvas_flag(db, enabled=True)
    stranger = make_user(db, email="stranger-skill@example.com")
    secret = _skill(db, stranger, title="未发布的秘密", status=CreationSkillStatus.DRAFT)
    canvas_id = _canvas(client, author)
    assert _drop_skill_card(client, author, canvas_id, secret.id).status_code == 200

    body = client.get(f"/v1/canvas-projects/{canvas_id}", headers=auth_header(author)).json()
    assert body["snapshot"]["skills"] == []
    # The card itself still exists — it just renders stale, which is the
    # honest outcome. Dropping the node would be silently editing the user's
    # canvas on read.
    assert len(body["nodes"]) == 1


def test_my_own_draft_skill_still_hydrates(client: TestClient, db: Session, author: User) -> None:
    """Same rule as `skill_library_service.get_usable`: a draft is visible to
    its owner. Someone building a skill should be able to lay it out on their
    canvas before publishing it."""
    _set_canvas_flag(db, enabled=True)
    mine = _skill(db, author, title="我的草稿", status=CreationSkillStatus.DRAFT)
    canvas_id = _canvas(client, author)
    assert _drop_skill_card(client, author, canvas_id, mine.id).status_code == 200

    body = client.get(f"/v1/canvas-projects/{canvas_id}", headers=auth_header(author)).json()
    assert [entry["id"] for entry in body["snapshot"]["skills"]] == [mine.id]


def test_rebinding_a_card_stops_hydrating_the_old_skill(
    client: TestClient, db: Session, author: User
) -> None:
    """`binding_skill_id` is denormalised out of `binding_json`. If an update
    wrote the JSON without clearing the column, the canvas would keep
    resolving a skill the card no longer points at."""
    _set_canvas_flag(db, enabled=True)
    first = _skill(db, author, title="第一个")
    second = _skill(db, author, title="第二个")
    canvas_id = _canvas(client, author)
    created = _drop_skill_card(client, author, canvas_id, first.id)
    assert created.status_code == 200
    change = created.json()["changes"][0]
    node_id = change["entity_id"]
    revision = change["payload"]["revision"]

    updated = client.post(
        f"/v1/canvas-projects/{canvas_id}/graph-ops",
        json={
            "base_seq": created.json()["change_seq"],
            "ops": [
                {
                    "op_id": "op_rebind",
                    "kind": "node.update",
                    "node_id": node_id,
                    "expected_revision": revision,
                    "binding": {"kind": "skill", "skill_id": second.id},
                }
            ],
        },
        headers=auth_header(author),
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["conflicts"] == []

    body = client.get(f"/v1/canvas-projects/{canvas_id}", headers=auth_header(author)).json()
    assert [entry["id"] for entry in body["snapshot"]["skills"]] == [second.id]
