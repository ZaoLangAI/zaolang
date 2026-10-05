"""Drafting a character's description / voice description from the scripts
that link it (`GET …/script-links`, `POST …/describe`)."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.characters import service as characters_service
from app.models import AgentRun, DramaEpisode, Series, SeriesCollaborator, User
from app.models.enums import SeriesCollaboratorStatus, SeriesStatus
from app.platform_config import service as config_service
from app.platform_config.schemas import FeatureFlags
from tests.conftest import auth_header
from tests.fake_llm_gateway import CHARACTER_DESCRIBE_EMPTY_MARKER


def _enable_script_studio(session: Session, actor: User) -> None:
    value = config_service.get_typed(session, "feature_flags", FeatureFlags).model_dump(mode="json")
    value["script_studio_enabled"] = True
    config_service.set_value(session, "feature_flags", value, actor_user_id=actor.id, note="test")


def _character(session: Session, owner: User, name: str = "林夏") -> str:
    view = characters_service.create_character(
        session,
        user_id=owner.id,
        name=name,
        description="作者自己写的旧描述",
        reference_asset_ids=[],
        voice_description=None,
    )
    session.flush()
    return view.id


def _script(character_id: str | None, *, name: str = "林夏", traits: str = "") -> dict[str, Any]:
    cast: dict[str, Any] = {"name": name, "traits": traits}
    if character_id:
        cast |= {"character_ref_id": character_id, "look_id": None}
    return {
        "title": "便利店的秘密",
        "logline": "深夜便利店里藏着一个秘密。",
        "characters": [cast, {"name": "路人", "traits": "中年男性"}],
        "scenes": [
            {
                "heading": "第一场 · 便利店 - 夜",
                "blocks": [
                    {"type": "dialogue", "character": name, "text": "今天，会是最后一天吗。"},
                    {"type": "dialogue", "character": "路人", "text": "结账。"},
                    {"type": "action", "character": None, "text": "她擦着柜台。"},
                    {"type": "dialogue", "character": name, "text": "欢迎光临。"},
                ],
            }
        ],
    }


def _episode(session: Session, owner: User, script: dict[str, Any], **series: Any) -> DramaEpisode:
    row = Series(owner_user_id=owner.id, title="夜班", kind="drama", **series)
    session.add(row)
    session.flush()
    episode = DramaEpisode(series_id=row.id, episode_number=1, title="第一集", script_json=script)
    session.add(episode)
    session.flush()
    return episode


def test_script_links_list_only_scripts_that_link_the_card(
    client: TestClient, db: Session, author: User
) -> None:
    _enable_script_studio(db, author)
    character_id = _character(db, author)
    linked = _episode(db, author, _script(character_id, traits="真人写实影视短剧造型，年轻女性"))
    _episode(db, author, _script(None))
    _episode(db, author, _script(character_id), status=SeriesStatus.TRASHED)

    response = client.get(
        f"/v1/characters/{character_id}/script-links", headers=auth_header(author)
    )
    assert response.status_code == 200
    body = response.json()
    assert [link["episode_id"] for link in body] == [linked.id]
    assert body[0]["character_name"] == "林夏"
    assert body[0]["dialogue_count"] == 2
    assert body[0]["series_title"] == "夜班"


def test_script_links_are_empty_while_the_script_studio_is_off(
    client: TestClient, db: Session, author: User
) -> None:
    character_id = _character(db, author)
    _episode(db, author, _script(character_id))
    response = client.get(
        f"/v1/characters/{character_id}/script-links", headers=auth_header(author)
    )
    assert response.status_code == 200
    assert response.json() == []


def test_describe_drafts_both_fields_without_saving(
    client: TestClient, db: Session, author: User
) -> None:
    _enable_script_studio(db, author)
    character_id = _character(db, author)
    traits = "真人写实影视短剧造型，年轻女性，齐肩黑发，便利店制服；外冷内热"
    episode = _episode(db, author, _script(character_id, traits=traits))

    response = client.post(
        f"/v1/characters/{character_id}/describe", json={}, headers=auth_header(author)
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["description"] == traits
    assert "2 句台词" in body["voice_description"]
    assert body["episode_ids"] == [episode.id]

    # A draft only: the card keeps the author's own text.
    card = client.get(f"/v1/characters/{character_id}", headers=auth_header(author)).json()
    assert card["description"] == "作者自己写的旧描述"
    assert card["voice_description"] is None
    run = db.scalars(select(AgentRun).order_by(AgentRun.created_at.desc())).first()
    assert run is not None and run.input_json is not None


def test_describe_can_ask_for_one_field_and_one_script(
    client: TestClient, db: Session, author: User
) -> None:
    _enable_script_studio(db, author)
    character_id = _character(db, author)
    first = _episode(db, author, _script(character_id, traits="旧剧本设定"))
    _episode(db, author, _script(character_id, traits="新剧本设定"))

    response = client.post(
        f"/v1/characters/{character_id}/describe",
        json={"episode_id": first.id, "fields": ["voice_description"]},
        headers=auth_header(author),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["description"] is None
    assert body["voice_description"]
    assert body["episode_ids"] == [first.id]


def test_describe_without_a_linked_script_is_a_422(
    client: TestClient, db: Session, author: User
) -> None:
    _enable_script_studio(db, author)
    character_id = _character(db, author)
    response = client.post(
        f"/v1/characters/{character_id}/describe", json={}, headers=auth_header(author)
    )
    assert response.status_code == 422
    assert "episode_id" in response.json()["error"]["details"]["fields"]


def test_describe_surfaces_an_unusable_draft_as_unavailable(
    client: TestClient, db: Session, author: User
) -> None:
    _enable_script_studio(db, author)
    name = f"{CHARACTER_DESCRIBE_EMPTY_MARKER}角色"
    character_id = _character(db, author, name=name)
    _episode(db, author, _script(character_id, name=name))
    response = client.post(
        f"/v1/characters/{character_id}/describe", json={}, headers=auth_header(author)
    )
    assert response.status_code == 503


def test_a_collaborators_script_counts_for_the_card_owner(
    client: TestClient, db: Session, author: User, remixer: User
) -> None:
    """The card is the remixer's; the script lives in the author's series the
    remixer co-creates — the remixer can draft from it."""
    _enable_script_studio(db, author)
    character_id = _character(db, remixer)
    episode = _episode(db, author, _script(character_id, traits="共创剧本设定"))
    db.add(
        SeriesCollaborator(
            series_id=episode.series_id,
            user_id=remixer.id,
            invited_by_user_id=author.id,
            status=SeriesCollaboratorStatus.ACTIVE,
        )
    )
    db.flush()
    response = client.post(
        f"/v1/characters/{character_id}/describe", json={}, headers=auth_header(remixer)
    )
    assert response.status_code == 200
    assert response.json()["description"] == "共创剧本设定"


def test_another_users_card_is_a_404(
    client: TestClient, db: Session, author: User, remixer: User
) -> None:
    _enable_script_studio(db, author)
    character_id = _character(db, author)
    for method, path in (
        ("get", f"/v1/characters/{character_id}/script-links"),
        ("post", f"/v1/characters/{character_id}/describe"),
    ):
        response = client.request(
            method, path, json={} if method == "post" else None, headers=auth_header(remixer)
        )
        assert response.status_code == 404
