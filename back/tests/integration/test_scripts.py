"""Script writing (文案创作): flag gating, streamed turns, versioning, skills."""

from __future__ import annotations

import json
from contextlib import contextmanager
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.domain.script_writing import service as script_writing_service
from app.models import User
from app.models.enums import CreationSkillCategory
from app.platform_config import service as config_service
from app.platform_config.schemas import FeatureFlags
from tests.conftest import auth_header


def _enable_script_studio(session: Session, actor: User) -> None:
    value = config_service.get_typed(session, "feature_flags", FeatureFlags).model_dump(mode="json")
    value["script_studio_enabled"] = True
    config_service.set_value(session, "feature_flags", value, actor_user_id=actor.id, note="test")


def _patch_stream_session(monkeypatch: pytest.MonkeyPatch, db: Session) -> None:
    """The streaming turn opens its own DB session so it survives past the
    request-scoped session's lifetime in production (see the module
    docstring in `app.domain.script_writing.service`). Tests run inside one
    rolled-back transaction, so — same technique `tests/integration/
    test_generation_lifecycle.py` uses for `app.workers.tasks` — point that
    session factory back at the shared `db` fixture instead."""

    @contextmanager
    def fake_session_scope():
        yield db

    monkeypatch.setattr(script_writing_service, "session_scope", fake_session_scope)


def _parse_sse(text: str) -> list[tuple[str, dict[str, Any]]]:
    events: list[tuple[str, dict[str, Any]]] = []
    for block in text.strip("\n").split("\n\n"):
        if not block.strip():
            continue
        lines = block.split("\n")
        event_line = next((line for line in lines if line.startswith("event: ")), None)
        data_line = next((line for line in lines if line.startswith("data: ")), None)
        if event_line is None or data_line is None:
            continue
        events.append((event_line[len("event: ") :], json.loads(data_line[len("data: ") :])))
    return events


def test_create_script_requires_flag(client: TestClient, author: User) -> None:
    response = client.post(
        "/v1/scripts",
        json={"title": "", "idea": "深夜便利店的秘密"},
        headers=auth_header(author),
    )
    assert response.status_code == 404


def test_create_script_streams_first_draft(
    client: TestClient, db: Session, author: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_script_studio(db, author)
    _patch_stream_session(monkeypatch, db)

    response = client.post(
        "/v1/scripts",
        json={"title": "", "idea": "深夜便利店的秘密"},
        headers=auth_header(author),
    )
    assert response.status_code == 202
    events = _parse_sse(response.text)
    kinds = [kind for kind, _ in events]
    assert kinds[0] == "start"
    assert "delta" in kinds
    assert kinds[-1] == "complete"

    complete = next(data for kind, data in events if kind == "complete")
    assert complete["turn_no"] == 1
    assert complete["script"]["scenes"]
    episode_id = complete["episode_id"]

    detail = client.get(f"/v1/scripts/{episode_id}", headers=auth_header(author))
    assert detail.status_code == 200
    body = detail.json()
    assert body["script"]["scenes"]
    assert len(body["turns"]) == 1
    assert body["turns"][0]["turn_no"] == 1


def test_create_script_surfaces_an_error_when_the_draft_fails_to_parse(
    client: TestClient, db: Session, author: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A first draft whose JSON never parses must not land as a turn with an
    empty-scenes script indistinguishable from a real, finished one — see
    `stream_new_script`'s `parse_ok` check."""
    from app.agents import copywriter
    from app.domain.script_writing import service as script_writing_service

    _enable_script_studio(db, author)
    _patch_stream_session(monkeypatch, db)

    def fake_stream_draft_script(*args: Any, **kwargs: Any) -> Any:
        def finalize() -> copywriter.ScriptTurnOutcome:
            return copywriter.ScriptTurnOutcome(
                summary="剧本生成失败，请换一种方式描述你的创意后重试。",
                script={"title": "t", "logline": "l", "characters": [], "scenes": []},
                parse_ok=False,
                degraded=False,
                model="stub",
                agent_run_id="agr_unused",
            )

        return iter(["部分输出"]), finalize

    monkeypatch.setattr(
        script_writing_service.copywriter, "stream_draft_script", fake_stream_draft_script
    )

    response = client.post(
        "/v1/scripts",
        json={"title": "", "idea": "深夜便利店的秘密"},
        headers=auth_header(author),
    )
    assert response.status_code == 202
    events = _parse_sse(response.text)
    kinds = [kind for kind, _ in events]
    assert kinds[0] == "start"
    assert kinds[-1] == "error"
    error = next(data for kind, data in events if kind == "error")
    assert error["message"]

    episode_id = next(data for kind, data in events if kind == "start")["episode_id"]
    detail = client.get(f"/v1/scripts/{episode_id}", headers=auth_header(author))
    assert detail.status_code == 200
    body = detail.json()
    assert body["turns"] == []
    assert body["script"]["scenes"] == []

    # Consistent with `list_scripts` treating a turn-less episode as not
    # actually started yet.
    listed = client.get("/v1/scripts", headers=auth_header(author))
    assert listed.json() == []


def test_revise_turn_versions_the_script(
    client: TestClient, db: Session, author: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_script_studio(db, author)
    _patch_stream_session(monkeypatch, db)

    created = client.post(
        "/v1/scripts",
        json={"title": "", "idea": "深夜便利店的秘密"},
        headers=auth_header(author),
    )
    first = next(data for kind, data in _parse_sse(created.text) if kind == "complete")
    episode_id = first["episode_id"]
    first_turn_id = first["turn_id"]

    revised = client.post(
        f"/v1/scripts/{episode_id}/turns",
        json={"message": "把结局改得更悬疑一点"},
        headers=auth_header(author),
    )
    assert revised.status_code == 202
    second = next(data for kind, data in _parse_sse(revised.text) if kind == "complete")
    assert second["turn_no"] == 2
    # The stub deterministically appends a scene containing the user's
    # message, so a real change is observable — not just an echo.
    scene_texts = [
        block["text"] for scene in second["script"]["scenes"] for block in scene["blocks"]
    ]
    assert any("把结局改得更悬疑一点" in text for text in scene_texts)

    detail = client.get(f"/v1/scripts/{episode_id}", headers=auth_header(author))
    turns = detail.json()["turns"]
    assert [t["turn_no"] for t in turns] == [1, 2]

    # The first turn's snapshot must still be exactly what it was — later
    # turns must never rewrite history.
    snapshot = client.get(
        f"/v1/scripts/{episode_id}/turns/{first_turn_id}/snapshot",
        headers=auth_header(author),
    )
    assert snapshot.status_code == 200
    assert len(snapshot.json()["script"]["scenes"]) == len(first["script"]["scenes"])


def test_referenced_skill_style_hint_reaches_the_prompt(
    client: TestClient, db: Session, author: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.domain.skill_library import service as skill_library_service
    from app.models import AgentRun

    _enable_script_studio(db, author)
    _patch_stream_session(monkeypatch, db)

    skill = skill_library_service.create(
        db,
        owner_user_id=author.id,
        title="赛博朋克夜色",
        description="霓虹雨夜，高对比色调，压抑而浪漫",
        category=CreationSkillCategory.STYLE,
        params_json={},
        cover_asset_id=None,
    )
    db.flush()

    response = client.post(
        "/v1/scripts",
        json={
            "title": "",
            "idea": "深夜便利店的秘密",
            "referenced_skill_ids": [skill.id],
        },
        headers=auth_header(author),
    )
    assert response.status_code == 202
    complete = next(data for kind, data in _parse_sse(response.text) if kind == "complete")

    from app.models import EpisodeScriptTurn

    turn = db.get(EpisodeScriptTurn, complete["turn_id"])
    assert turn is not None and turn.agent_run_id is not None
    run = db.get(AgentRun, turn.agent_run_id)
    assert run is not None
    assert "赛博朋克夜色" in json.dumps(run.input_json, ensure_ascii=False)

    db.refresh(skill)
    assert skill.usage_count == 1


def test_revise_turn_builds_on_the_client_supplied_current_script(
    client: TestClient, db: Session, author: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A turn sent while the user has browsed back to an earlier version in
    the UI (`ScriptEditor.selectTurn`) must build on top of *that* version,
    not silently jump to the episode's true latest turn underneath them."""
    _enable_script_studio(db, author)
    _patch_stream_session(monkeypatch, db)

    created = client.post(
        "/v1/scripts",
        json={"title": "", "idea": "深夜便利店的秘密"},
        headers=auth_header(author),
    )
    first = next(data for kind, data in _parse_sse(created.text) if kind == "complete")
    episode_id = first["episode_id"]
    first_script = first["script"]

    # Moves the true latest turn ahead of `first_script` — turn 2 now has
    # one more scene than `first_script` did.
    client.post(
        f"/v1/scripts/{episode_id}/turns",
        json={"message": "第一次修改"},
        headers=auth_header(author),
    )

    third = client.post(
        f"/v1/scripts/{episode_id}/turns",
        json={"message": "基于第一版继续修改", "current_script": first_script},
        headers=auth_header(author),
    )
    assert third.status_code == 202
    third_complete = next(data for kind, data in _parse_sse(third.text) if kind == "complete")
    assert third_complete["turn_no"] == 3
    # The stub only ever appends one scene per turn onto whatever
    # `current_script` it received. Starting again from `first_script`
    # yields exactly one more scene than `first_script` had — two more
    # would mean it silently built on the true latest (turn 2) instead.
    assert len(third_complete["script"]["scenes"]) == len(first_script["scenes"]) + 1


def test_update_links_patches_the_document_without_creating_a_turn(
    client: TestClient, db: Session, author: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.domain.characters import service as characters_service
    from app.domain.scenes import service as scenes_service

    _enable_script_studio(db, author)
    _patch_stream_session(monkeypatch, db)

    character = characters_service.create_character(
        db,
        user_id=author.id,
        name="小雨",
        description=None,
        reference_asset_ids=[],
        voice_description=None,
    )
    scene = scenes_service.create_scene(
        db, user_id=author.id, name="便利店", description=None, reference_asset_ids=[]
    )
    db.flush()

    created = client.post(
        "/v1/scripts",
        json={"title": "", "idea": "深夜便利店的秘密"},
        headers=auth_header(author),
    )
    first = next(data for kind, data in _parse_sse(created.text) if kind == "complete")
    episode_id = first["episode_id"]
    character_name = first["script"]["characters"][0]["name"]
    scene_heading = first["script"]["scenes"][0]["heading"]

    linked = client.patch(
        f"/v1/scripts/{episode_id}/links",
        json={
            "characters": [{"name": character_name, "character_ref_id": character.id}],
            "scenes": [{"heading": scene_heading, "ref_id": scene.id}],
        },
        headers=auth_header(author),
    )
    assert linked.status_code == 200
    body = linked.json()
    assert body["characters"][0]["character_ref_id"] == character.id
    assert body["scenes"][0]["ref_id"] == scene.id

    # A structural link must never create a new conversation turn.
    detail = client.get(f"/v1/scripts/{episode_id}", headers=auth_header(author))
    assert len(detail.json()["turns"]) == 1

    # The link must survive a later revision turn even though the model's
    # own output never mentions `character_ref_id`/`ref_id`.
    revised = client.post(
        f"/v1/scripts/{episode_id}/turns",
        json={"message": "继续修改"},
        headers=auth_header(author),
    )
    revised_complete = next(data for kind, data in _parse_sse(revised.text) if kind == "complete")
    revised_character = next(
        c for c in revised_complete["script"]["characters"] if c["name"] == character_name
    )
    assert revised_character["character_ref_id"] == character.id


def test_list_scripts_only_shows_started_scripts(
    client: TestClient, db: Session, author: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_script_studio(db, author)
    _patch_stream_session(monkeypatch, db)

    empty_list = client.get("/v1/scripts", headers=auth_header(author))
    assert empty_list.status_code == 200
    assert empty_list.json() == []

    client.post(
        "/v1/scripts",
        json={"title": "", "idea": "深夜便利店的秘密"},
        headers=auth_header(author),
    )

    populated = client.get("/v1/scripts", headers=auth_header(author))
    assert len(populated.json()) == 1
    assert populated.json()[0]["turn_count"] == 1
