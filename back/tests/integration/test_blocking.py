"""白膜 studio: flag gating, streamed build/turns, bidirectional script sync,
manual saves with optimistic concurrency, and staleness."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1 import blocking as blocking_api
from app.api.v1 import scripts as scripts_api
from app.domain.blocking import service as blocking_service
from app.domain.script_writing import service as script_writing_service
from app.models import EpisodeBlockingVersion, EpisodeScriptTurn, User
from app.platform_config import service as config_service
from app.platform_config.schemas import FeatureFlags
from tests.conftest import auth_header
from tests.integration.test_scripts import _parse_sse


def _enable(session: Session, actor: User, *, blocking: bool = True) -> None:
    value = config_service.get_typed(session, "feature_flags", FeatureFlags).model_dump(mode="json")
    value["script_studio_enabled"] = True
    value["blocking_studio_enabled"] = blocking
    config_service.set_value(session, "feature_flags", value, actor_user_id=actor.id, note="test")


@pytest.fixture
def shared_session(monkeypatch: pytest.MonkeyPatch, db: Session) -> Session:
    """Every stream window (`session_scope`) reuses the test's rolled-back
    transaction — see `test_scripts._patch_stream_session`."""

    @contextmanager
    def fake_session_scope():
        yield db

    for module in (script_writing_service, blocking_service, blocking_api, scripts_api):
        monkeypatch.setattr(module, "session_scope", fake_session_scope)
    return db


def _new_script(client: TestClient, author: User) -> dict[str, Any]:
    response = client.post(
        "/v1/scripts", json={"title": "", "idea": "深夜便利店的秘密"}, headers=auth_header(author)
    )
    events = _parse_sse(response.text)
    return next(data for kind, data in events if kind == "complete")


def _complete(response: Any) -> dict[str, Any]:
    events = _parse_sse(response.text)
    assert events[-1][0] == "complete", events
    return events[-1][1]


def test_blocking_routes_require_the_flag(
    client: TestClient, db: Session, author: User, shared_session: Session
) -> None:
    _enable(db, author, blocking=False)
    draft = _new_script(client, author)
    episode_id = draft["episode_id"]

    rebuild = client.post(f"/v1/scripts/{episode_id}/blocking:rebuild", headers=auth_header(author))
    assert rebuild.status_code == 404
    detail = client.get(f"/v1/scripts/{episode_id}", headers=auth_header(author)).json()
    assert detail["blocking"] is None

    me = client.get("/v1/auth/me", headers=auth_header(author)).json()
    assert me["features"]["blocking_studio"] is False


def test_rebuild_streams_phases_and_persists_a_version(
    client: TestClient, db: Session, author: User, shared_session: Session
) -> None:
    _enable(db, author)
    episode_id = _new_script(client, author)["episode_id"]

    detail = client.get(f"/v1/scripts/{episode_id}", headers=auth_header(author)).json()
    assert detail["blocking"]["document"] is None
    assert detail["blocking"]["version_no"] == 0
    assert detail["blocking"]["default_target_duration_seconds"] > 0

    response = client.post(
        f"/v1/scripts/{episode_id}/blocking:rebuild", headers=auth_header(author)
    )
    assert response.status_code == 202
    events = _parse_sse(response.text)
    phases = [data["name"] for kind, data in events if kind == "phase"]
    # A rebuild never routes or touches the script.
    assert phases == ["blocking"]
    complete = _complete(response)
    state = complete["blocking"]
    assert state["version_no"] == 1
    assert state["stale"] is False
    document = state["document"]
    assert [c["name"] for c in document["cast"]] == ["林夏"]
    assert document["segments"][0]["beats"][0]["action"] == "walk"
    assert complete["turn_id"] is None

    versions = list(
        db.scalars(
            select(EpisodeBlockingVersion).where(EpisodeBlockingVersion.episode_id == episode_id)
        )
    )
    assert [(v.version_no, v.origin) for v in versions] == [(1, "rebuild")]


def test_staging_only_turn_keeps_the_script_and_records_a_blocking_turn(
    client: TestClient, db: Session, author: User, shared_session: Session
) -> None:
    _enable(db, author)
    draft = _new_script(client, author)
    episode_id = draft["episode_id"]
    client.post(f"/v1/scripts/{episode_id}/blocking:rebuild", headers=auth_header(author))

    response = client.post(
        f"/v1/scripts/{episode_id}/blocking/turns",
        json={"message": "镜头改成环绕"},
        headers=auth_header(author),
    )
    events = _parse_sse(response.text)
    assert [d["name"] for k, d in events if k == "phase"] == ["route", "blocking"]
    complete = _complete(response)
    assert complete["script_changed"] is False
    assert complete["script"] == draft["script"]
    assert complete["blocking"]["version_no"] == 2
    moves = {s["shot"]["move"]["preset"] for s in complete["blocking"]["document"]["segments"]}
    assert moves == {"orbit_cw"}

    turn = db.get(EpisodeScriptTurn, complete["turn_id"])
    assert turn is not None
    assert turn.origin == "blocking"
    detail = client.get(f"/v1/scripts/{episode_id}", headers=auth_header(author)).json()
    assert [t["origin"] for t in detail["turns"]] == ["script", "blocking"]


def test_script_touching_turn_rewrites_the_script_then_restages(
    client: TestClient, db: Session, author: User, shared_session: Session
) -> None:
    _enable(db, author)
    draft = _new_script(client, author)
    episode_id = draft["episode_id"]
    client.post(f"/v1/scripts/{episode_id}/blocking:rebuild", headers=auth_header(author))

    response = client.post(
        f"/v1/scripts/{episode_id}/blocking/turns",
        json={"message": "新增一场天台对白"},
        headers=auth_header(author),
    )
    events = _parse_sse(response.text)
    assert [d["name"] for k, d in events if k == "phase"] == ["route", "script", "blocking"]
    complete = _complete(response)
    assert complete["script_changed"] is True
    # The fake revision appends a scene; the blockout follows it.
    assert len(complete["script"]["scenes"]) == len(draft["script"]["scenes"]) + 1
    keys = [s["key"] for s in complete["blocking"]["document"]["segments"]]
    assert keys[-1].startswith(complete["script"]["scenes"][-1]["heading"])
    assert complete["blocking"]["stale"] is False

    detail = client.get(f"/v1/scripts/{episode_id}", headers=auth_header(author)).json()
    assert detail["script"] == complete["script"]


def test_script_edit_marks_the_blockout_stale(
    client: TestClient, db: Session, author: User, shared_session: Session
) -> None:
    _enable(db, author)
    draft = _new_script(client, author)
    episode_id = draft["episode_id"]
    client.post(f"/v1/scripts/{episode_id}/blocking:rebuild", headers=auth_header(author))

    script = draft["script"]
    script["scenes"][0]["blocks"][3]["text"] = "（低声）明天见。"
    client.patch(f"/v1/scripts/{episode_id}", json={"script": script}, headers=auth_header(author))
    state = client.get(f"/v1/scripts/{episode_id}", headers=auth_header(author)).json()["blocking"]
    assert state["stale"] is True
    assert state["stale_segment_keys"] == [f"{script['scenes'][0]['heading']}#0"]

    rebuilt = _complete(
        client.post(f"/v1/scripts/{episode_id}/blocking:rebuild", headers=auth_header(author))
    )
    assert rebuilt["blocking"]["stale"] is False


def test_manual_save_coalesces_and_rejects_a_stale_base(
    client: TestClient, db: Session, author: User, shared_session: Session
) -> None:
    _enable(db, author)
    episode_id = _new_script(client, author)["episode_id"]
    built = _complete(
        client.post(f"/v1/scripts/{episode_id}/blocking:rebuild", headers=auth_header(author))
    )["blocking"]
    document = built["document"]
    document["sets"][0]["props"][0]["position"] = [1.0, 0.5, -1.0]

    first = client.patch(
        f"/v1/scripts/{episode_id}/blocking",
        json={"document": document, "base_version_no": 1},
        headers=auth_header(author),
    )
    assert first.status_code == 200
    assert first.json()["version_no"] == 2
    assert first.json()["document"]["sets"][0]["props"][0]["position"] == [1.0, 0.5, -1.0]

    document["segments"][0]["camera_override"] = {
        "start": {"position": [0, 1.6, 4], "target": [0, 1.2, 0], "fov": 30},
        "end": None,
    }
    second = client.patch(
        f"/v1/scripts/{episode_id}/blocking",
        json={"document": document, "base_version_no": 2},
        headers=auth_header(author),
    )
    # A second drag right after the first folds into the same version.
    assert second.json()["version_no"] == 2
    assert second.json()["document"]["segments"][0]["camera_override"]["start"]["fov"] == 30.0

    stale = client.patch(
        f"/v1/scripts/{episode_id}/blocking",
        json={"document": document, "base_version_no": 1},
        headers=auth_header(author),
    )
    assert stale.status_code == 409


def test_settings_refit_durations_without_a_model_call(
    client: TestClient, db: Session, author: User, shared_session: Session
) -> None:
    _enable(db, author)
    episode_id = _new_script(client, author)["episode_id"]
    _complete(
        client.post(f"/v1/scripts/{episode_id}/blocking:rebuild", headers=auth_header(author))
    )

    response = client.patch(
        f"/v1/scripts/{episode_id}/blocking/settings",
        json={"target_duration_seconds": 12, "aspect_ratio": "16:9", "base_version_no": 1},
        headers=auth_header(author),
    )
    assert response.status_code == 200
    state = response.json()
    assert state["target_duration_seconds"] == 12
    assert state["document"]["aspect_ratio"] == "16:9"
    assert sum(s["duration_s"] for s in state["document"]["segments"]) == 12

    version = client.get(
        f"/v1/scripts/{episode_id}/blocking/versions/1", headers=auth_header(author)
    )
    assert version.status_code == 200
    assert version.json()["origin"] == "rebuild"


def test_turn_needs_a_script_first(
    client: TestClient, db: Session, author: User, shared_session: Session
) -> None:
    _enable(db, author)
    other = client.post(
        "/v1/scripts/dep_missing/blocking/turns",
        json={"message": "hi"},
        headers=auth_header(author),
    )
    assert other.status_code == 404
