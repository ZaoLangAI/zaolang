"""Script writing (文案创作): flag gating, streamed turns, versioning, skills."""

from __future__ import annotations

import json
from contextlib import contextmanager
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.script_writing import service as script_writing_service
from app.llm.client import StreamChunk
from app.models import DramaEpisode, Notification, User
from app.models.enums import CreationSkillCategory, NotificationType
from app.platform_config import service as config_service
from app.platform_config.schemas import FeatureFlags
from tests.conftest import auth_header


def _script_notes(db: Session, user: User, episode_id: str) -> list[Notification]:
    return list(
        db.scalars(
            select(Notification).where(
                Notification.user_id == user.id,
                Notification.target_type == "episode_script",
                Notification.target_id == episode_id,
            )
        )
    )


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
    # The fake gateway (`tests/fake_llm_gateway.py::fake_stream_complete`)
    # yields one `thinking` chunk before its `content` — the live reasoning
    # channel must reach the SSE body as its own event, not get folded into
    # `delta`.
    assert "thinking" in kinds
    assert kinds[-1] == "complete"

    complete = next(data for kind, data in events if kind == "complete")
    assert complete["turn_no"] == 1
    assert complete["script"]["scenes"]
    assert complete["thinking"]
    episode_id = complete["episode_id"]

    detail = client.get(f"/v1/scripts/{episode_id}", headers=auth_header(author))
    assert detail.status_code == 200
    body = detail.json()
    assert body["script"]["scenes"]
    assert len(body["turns"]) == 1
    assert body["turns"][0]["turn_no"] == 1
    # Persisted on the turn (`EpisodeScriptTurn.thinking_text`), surfaced via
    # `ScriptTurnSummary.thinking` — not just present in the one-shot
    # `complete` frame.
    assert body["turns"][0]["thinking"]


def test_create_script_upserts_generating_then_succeeded_notification(
    client: TestClient, db: Session, author: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Full lifecycle for a script's first draft: `prepare_new_script`
    fires a `"generating"` notification (never actionable — no unread bump/
    push), and the finished turn upserts that same row to `"succeeded"`
    (which is)."""
    _enable_script_studio(db, author)
    _patch_stream_session(monkeypatch, db)

    response = client.post(
        "/v1/scripts",
        json={"title": "", "idea": "深夜便利店的秘密"},
        headers=auth_header(author),
    )
    complete = next(data for kind, data in _parse_sse(response.text) if kind == "complete")
    episode_id = complete["episode_id"]

    notes = _script_notes(db, author, episode_id)
    assert len(notes) == 1
    note = notes[0]
    assert note.type == NotificationType.JOB_SUCCEEDED
    assert note.title_key == "notification.script_succeeded"
    assert note.payload_json["kind"] == "draft"
    assert note.payload_json["turn_no"] == 1
    assert note.payload_json["episode_id"] == episode_id
    assert note.read_at is None


def test_revise_turn_upserts_the_same_script_notification_row(
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
    first_note_id = _script_notes(db, author, episode_id)[0].id

    revised = client.post(
        f"/v1/scripts/{episode_id}/turns",
        json={"message": "把结局改得更悬疑一点"},
        headers=auth_header(author),
    )
    assert revised.status_code == 202

    notes = _script_notes(db, author, episode_id)
    assert len(notes) == 1
    note = notes[0]
    assert note.id == first_note_id
    assert note.type == NotificationType.JOB_SUCCEEDED
    assert note.title_key == "notification.script_succeeded"
    assert note.payload_json["kind"] == "revise"
    assert note.payload_json["turn_no"] == 2


def test_create_script_replay_with_the_same_idempotency_key_preserves_thinking(
    client: TestClient, db: Session, author: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A retried request with the same `Idempotency-Key` replays the stored
    `complete` snapshot instead of re-running the LLM turn (no `delta`/
    `thinking` frames in front of it — see `_replay_stream`) — but that
    snapshot must still carry `thinking`, or the replayed frame would look
    unlike the original live one to the frontend."""
    from app.api.v1 import scripts as scripts_module

    _enable_script_studio(db, author)
    _patch_stream_session(monkeypatch, db)
    # `_remember_idempotent` deliberately opens its own session via
    # `app.db.session_scope` (see its docstring) rather than reusing the
    # route's own — in production that session's a separate, later-committed
    # connection to the same already-committed rows; here it would instead
    # be a second, genuinely separate connection racing the still-open
    # `db` fixture transaction that `author` only exists in, so point it
    # back at `db` too, same as `_patch_stream_session` does for the
    # streaming turn's own session.
    @contextmanager
    def fake_session_scope():
        yield db

    monkeypatch.setattr(scripts_module, "session_scope", fake_session_scope)

    headers = {**auth_header(author), "Idempotency-Key": "idk-script-replay"}
    payload = {"title": "", "idea": "深夜便利店的秘密"}

    first = client.post("/v1/scripts", json=payload, headers=headers)
    assert first.status_code == 202
    first_events = _parse_sse(first.text)
    assert "thinking" in [kind for kind, _ in first_events]
    first_complete = next(data for kind, data in first_events if kind == "complete")
    assert first_complete["thinking"]

    second = client.post("/v1/scripts", json=payload, headers=headers)
    assert second.status_code == 202
    second_events = _parse_sse(second.text)
    # The replay is a single `complete` frame — no re-run of the turn.
    assert [kind for kind, _ in second_events] == ["complete"]
    second_complete = next(data for kind, data in second_events if kind == "complete")
    assert second_complete == first_complete

    episodes = client.get("/v1/scripts", headers=auth_header(author)).json()
    assert len(episodes) == 1


def test_create_script_attaches_to_existing_series(
    client: TestClient, db: Session, author: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """"新增一集" from an existing series' detail page must attach the new
    episode to that series (auto-incrementing episode_number), not spin up a
    second series."""
    _enable_script_studio(db, author)
    _patch_stream_session(monkeypatch, db)

    from app.domain.editor import service as editor_service

    series = editor_service.create_drama_series(
        db, user_id=author.id, title="我的短剧", target_platforms=["manual_download"]
    )
    editor_service.create_episode(db, user_id=author.id, series_id=series.id, title="第一集")
    db.commit()

    response = client.post(
        "/v1/scripts",
        json={"title": "", "idea": "深夜便利店的秘密", "series_id": series.id},
        headers=auth_header(author),
    )
    assert response.status_code == 202
    events = _parse_sse(response.text)
    complete = next(data for kind, data in events if kind == "complete")
    episode_id = complete["episode_id"]

    detail = client.get(f"/v1/scripts/{episode_id}", headers=auth_header(author))
    assert detail.status_code == 200
    body = detail.json()
    assert body["series_id"] == series.id

    episodes = editor_service.list_episodes(db, user_id=author.id, series_id=series.id)
    assert [ep.episode_number for ep in episodes] == [1, 2]


def test_create_script_rejects_someone_elses_series(
    client: TestClient, db: Session, author: User
) -> None:
    from app.domain.editor import service as editor_service
    from tests.conftest import make_user

    _enable_script_studio(db, author)
    outsider = make_user(db, email="script-outsider@example.com", handle="scriptoutsider")
    series = editor_service.create_drama_series(
        db, user_id=outsider.id, title="别人的短剧", target_platforms=["manual_download"]
    )
    db.commit()

    response = client.post(
        "/v1/scripts",
        json={"title": "", "idea": "深夜便利店的秘密", "series_id": series.id},
        headers=auth_header(author),
    )
    assert response.status_code == 404


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
        def finalize(_persist_session: Any = None) -> copywriter.ScriptTurnOutcome:
            return copywriter.ScriptTurnOutcome(
                summary="剧本生成失败，请换一种方式描述你的创意后重试。",
                script={"title": "t", "logline": "l", "characters": [], "scenes": []},
                parse_ok=False,
                degraded=False,
                model="stub",
                agent_run_id="agr_unused",
            )

        return iter([StreamChunk(kind="content", text="部分输出")]), finalize

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
    assert body["source_idea"] == "深夜便利店的秘密"
    assert body["last_error"]

    # `list_scripts` no longer requires a turn to exist — a failed first
    # draft must stay discoverable (and retryable) rather than vanishing.
    listed = client.get("/v1/scripts", headers=auth_header(author))
    assert len(listed.json()) == 1
    assert listed.json()[0]["episode_id"] == episode_id
    assert listed.json()[0]["turn_count"] == 0

    notes = _script_notes(db, author, episode_id)
    assert len(notes) == 1
    assert notes[0].type == NotificationType.JOB_FAILED
    assert notes[0].title_key == "notification.script_failed"
    assert notes[0].payload_json["kind"] == "draft"
    assert notes[0].payload_json["error"]
    assert notes[0].read_at is None


def test_create_script_empty_stream_does_not_write_a_turn(
    client: TestClient, db: Session, author: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A reasoning model that returns no visible tokens after retry must
    surface as an in-stream error, not a turn with an empty document."""
    from app.llm import client as llm_client

    _enable_script_studio(db, author)
    _patch_stream_session(monkeypatch, db)

    def empty_stream(**kwargs: Any) -> Any:
        kwargs["result"].text = ""
        yield from ()

    monkeypatch.setattr(llm_client, "stream_complete", empty_stream)

    response = client.post(
        "/v1/scripts",
        json={"title": "", "idea": "深夜便利店的秘密"},
        headers=auth_header(author),
    )
    assert response.status_code == 202
    events = _parse_sse(response.text)
    assert next(kind for kind, _ in events) == "start"
    assert events[-1][0] == "error"

    episode_id = next(data for kind, data in events if kind == "start")["episode_id"]
    detail = client.get(f"/v1/scripts/{episode_id}", headers=auth_header(author))
    assert detail.json()["turns"] == []
    assert detail.json()["script"]["scenes"] == []


def test_retry_script_regenerates_the_first_draft_for_an_empty_shell(
    client: TestClient, db: Session, author: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The empty-shell recovery path: a first draft never finished (the
    fake stream below stands in for a dropped connection/failed parse), so
    `POST /v1/scripts/{episode_id}/retry` re-runs it on the *same* episode
    rather than `POST /v1/scripts` minting a second one."""
    from app.llm import client as llm_client

    _enable_script_studio(db, author)
    _patch_stream_session(monkeypatch, db)

    def empty_stream(**kwargs: Any) -> Any:
        kwargs["result"].text = ""
        yield from ()

    monkeypatch.setattr(llm_client, "stream_complete", empty_stream)

    failed = client.post(
        "/v1/scripts",
        json={"title": "", "idea": "深夜便利店的秘密"},
        headers=auth_header(author),
    )
    start_data = next(data for kind, data in _parse_sse(failed.text) if kind == "start")
    episode_id = start_data["episode_id"]
    detail = client.get(f"/v1/scripts/{episode_id}", headers=auth_header(author))
    assert detail.json()["turns"] == []

    # Undoes only the `empty_stream` override above, back to the module's
    # own autouse `fake_stream_complete` (not `monkeypatch.undo()`, which
    # would also revert *that* fixture's patch — the two share this same
    # `monkeypatch` instance for the whole test).
    from tests.fake_llm_gateway import fake_stream_complete

    monkeypatch.setattr(llm_client, "stream_complete", fake_stream_complete)

    retried = client.post(
        f"/v1/scripts/{episode_id}/retry",
        json={"idea": "深夜便利店的秘密，换一种写法"},
        headers=auth_header(author),
    )
    assert retried.status_code == 202
    events = _parse_sse(retried.text)
    kinds = [kind for kind, _ in events]
    assert kinds[0] == "start"
    assert kinds[-1] == "complete"
    complete = next(data for kind, data in events if kind == "complete")
    assert complete["episode_id"] == episode_id
    assert complete["turn_no"] == 1

    detail = client.get(f"/v1/scripts/{episode_id}", headers=auth_header(author))
    body = detail.json()
    assert len(body["turns"]) == 1
    assert body["script"]["scenes"]

    # No second episode/series was created along the way.
    listed = client.get("/v1/scripts", headers=auth_header(author))
    assert len(listed.json()) == 1


def test_retry_script_reuses_stored_idea_when_body_omits_it(
    client: TestClient, db: Session, author: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed first draft already persisted `source_idea` — retry must
    not demand the author type it again."""
    from app.llm import client as llm_client
    from tests.fake_llm_gateway import fake_stream_complete

    _enable_script_studio(db, author)
    _patch_stream_session(monkeypatch, db)

    def empty_stream(**kwargs: Any) -> Any:
        kwargs["result"].text = ""
        yield from ()

    monkeypatch.setattr(llm_client, "stream_complete", empty_stream)

    failed = client.post(
        "/v1/scripts",
        json={"title": "", "idea": "深夜便利店的秘密"},
        headers=auth_header(author),
    )
    episode_id = next(data for kind, data in _parse_sse(failed.text) if kind == "start")[
        "episode_id"
    ]
    assert client.get(f"/v1/scripts/{episode_id}", headers=auth_header(author)).json()[
        "source_idea"
    ] == "深夜便利店的秘密"

    monkeypatch.setattr(llm_client, "stream_complete", fake_stream_complete)

    retried = client.post(
        f"/v1/scripts/{episode_id}/retry",
        json={},
        headers=auth_header(author),
    )
    assert retried.status_code == 202
    events = _parse_sse(retried.text)
    assert [kind for kind, _ in events][0] == "start"
    assert [kind for kind, _ in events][-1] == "complete"
    complete = next(data for kind, data in events if kind == "complete")
    assert complete["episode_id"] == episode_id
    assert complete["turn_no"] == 1
    detail = client.get(f"/v1/scripts/{episode_id}", headers=auth_header(author)).json()
    assert len(detail["turns"]) == 1
    assert detail["turns"][0]["user_message"] == "深夜便利店的秘密"
    assert detail["last_error"] is None


def test_get_script_recovers_source_idea_from_a_nearby_agent_run(
    client: TestClient, db: Session, author: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Shells created before `source_idea` existed still one-click retry
    after GET backfills the prompt from the original `script_draft` run."""
    from app.llm import client as llm_client

    _enable_script_studio(db, author)
    _patch_stream_session(monkeypatch, db)

    def empty_stream(**kwargs: Any) -> Any:
        kwargs["result"].text = ""
        yield from ()

    monkeypatch.setattr(llm_client, "stream_complete", empty_stream)

    failed = client.post(
        "/v1/scripts",
        json={"title": "", "idea": "深夜便利店的秘密"},
        headers=auth_header(author),
    )
    episode_id = next(data for kind, data in _parse_sse(failed.text) if kind == "start")[
        "episode_id"
    ]
    episode = db.get(DramaEpisode, episode_id)
    assert episode is not None
    episode.source_idea = None
    episode.source_referenced_skill_ids_json = []
    db.flush()

    body = client.get(f"/v1/scripts/{episode_id}", headers=auth_header(author)).json()
    assert body["source_idea"] == "深夜便利店的秘密"


def test_retry_script_rejects_an_episode_that_already_has_a_turn(
    client: TestClient, db: Session, author: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_script_studio(db, author)
    _patch_stream_session(monkeypatch, db)

    created = client.post(
        "/v1/scripts",
        json={"title": "", "idea": "深夜便利店的秘密"},
        headers=auth_header(author),
    )
    episode_id = next(data for kind, data in _parse_sse(created.text) if kind == "complete")[
        "episode_id"
    ]

    response = client.post(
        f"/v1/scripts/{episode_id}/retry",
        json={"idea": "换个新故事"},
        headers=auth_header(author),
    )
    assert response.status_code == 422


def test_retry_script_rejects_another_users_episode(
    client: TestClient, db: Session, author: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.llm import client as llm_client
    from tests.conftest import make_user

    _enable_script_studio(db, author)
    _patch_stream_session(monkeypatch, db)

    def empty_stream(**kwargs: Any) -> Any:
        kwargs["result"].text = ""
        yield from ()

    monkeypatch.setattr(llm_client, "stream_complete", empty_stream)
    failed = client.post(
        "/v1/scripts",
        json={"title": "", "idea": "深夜便利店的秘密"},
        headers=auth_header(author),
    )
    start_data = next(data for kind, data in _parse_sse(failed.text) if kind == "start")
    episode_id = start_data["episode_id"]

    outsider = make_user(db, email="retry-outsider@example.com", handle="retryoutsider")
    _enable_script_studio(db, outsider)
    db.commit()

    response = client.post(
        f"/v1/scripts/{episode_id}/retry",
        json={"idea": "换个新故事"},
        headers=auth_header(outsider),
    )
    assert response.status_code == 404


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


def test_update_content_saves_hand_edited_text_without_creating_a_turn(
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
    script = first["script"]
    script["logline"] = "手动修改后的梗概"
    script["scenes"][0]["blocks"][0]["text"] = "手动改写的第一句台词"

    saved = client.patch(
        f"/v1/scripts/{episode_id}",
        json={"script": script},
        headers=auth_header(author),
    )
    assert saved.status_code == 200
    body = saved.json()
    assert body["logline"] == "手动修改后的梗概"
    assert body["scenes"][0]["blocks"][0]["text"] == "手动改写的第一句台词"

    # A direct content save must never create a new conversation turn.
    detail = client.get(f"/v1/scripts/{episode_id}", headers=auth_header(author))
    assert len(detail.json()["turns"]) == 1
    assert detail.json()["script"]["logline"] == "手动修改后的梗概"

    # The hand-edit must be what the *next* prompt-based turn builds on, even
    # when the client doesn't resend `current_script` explicitly — it falls
    # back to the freshly-persisted `episode.script_json`, and the fake
    # gateway's revise stub only ever appends a scene onto whatever it's
    # handed, leaving earlier scenes/blocks untouched.
    revised = client.post(
        f"/v1/scripts/{episode_id}/turns",
        json={"message": "继续修改"},
        headers=auth_header(author),
    )
    revised_complete = next(data for kind, data in _parse_sse(revised.text) if kind == "complete")
    assert revised_complete["script"]["scenes"][0]["blocks"][0]["text"] == "手动改写的第一句台词"


def test_update_content_rejects_another_users_episode(
    client: TestClient, db: Session, author: User, remixer: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_script_studio(db, author)
    _enable_script_studio(db, remixer)
    _patch_stream_session(monkeypatch, db)

    created = client.post(
        "/v1/scripts",
        json={"title": "", "idea": "深夜便利店的秘密"},
        headers=auth_header(author),
    )
    first = next(data for kind, data in _parse_sse(created.text) if kind == "complete")
    episode_id = first["episode_id"]
    script = first["script"]
    script["logline"] = "别人偷改的梗概"

    response = client.patch(
        f"/v1/scripts/{episode_id}",
        json={"script": script},
        headers=auth_header(remixer),
    )
    assert response.status_code == 404

    # Untouched — still there for the real owner.
    detail = client.get(f"/v1/scripts/{episode_id}", headers=auth_header(author))
    assert detail.json()["script"]["logline"] != "别人偷改的梗概"


def test_update_content_requires_flag(client: TestClient, author: User) -> None:
    response = client.patch(
        "/v1/scripts/dep_missing",
        json={"script": {"title": "", "logline": "", "characters": [], "scenes": []}},
        headers=auth_header(author),
    )
    assert response.status_code == 404


def test_delete_script_removes_episode_and_turns(
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

    from app.models import DramaEpisode, EpisodeScriptTurn, Series

    series_id = db.get(DramaEpisode, episode_id).series_id

    response = client.delete(f"/v1/scripts/{episode_id}", headers=auth_header(author))
    assert response.status_code == 204

    assert db.get(DramaEpisode, episode_id) is None
    assert (
        db.scalar(
            select(func.count(EpisodeScriptTurn.id)).where(
                EpisodeScriptTurn.episode_id == episode_id
            )
        )
        == 0
    )
    # The 1:1 `Series` created for this script goes away too, once it is the
    # episode's only one.
    assert db.get(Series, series_id) is None

    listed = client.get("/v1/scripts", headers=auth_header(author))
    assert listed.json() == []


def test_delete_script_rejects_another_users_episode(
    client: TestClient, db: Session, author: User, remixer: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_script_studio(db, author)
    _enable_script_studio(db, remixer)
    _patch_stream_session(monkeypatch, db)

    created = client.post(
        "/v1/scripts",
        json={"title": "", "idea": "深夜便利店的秘密"},
        headers=auth_header(author),
    )
    episode_id = next(data for kind, data in _parse_sse(created.text) if kind == "complete")[
        "episode_id"
    ]

    response = client.delete(f"/v1/scripts/{episode_id}", headers=auth_header(remixer))
    assert response.status_code == 404

    # Untouched — still there for the real owner.
    detail = client.get(f"/v1/scripts/{episode_id}", headers=auth_header(author))
    assert detail.status_code == 200


def test_delete_script_blocked_once_opened_in_the_editor(
    client: TestClient, db: Session, author: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Once an `EpisodeCut` exists, deleting outright would hit the DB's own
    `RESTRICT` on `episode_cuts.episode_id` — `delete_script` must catch this
    itself and leave everything intact."""
    from app.models import DramaEpisode, EpisodeCut

    _enable_script_studio(db, author)
    _patch_stream_session(monkeypatch, db)

    created = client.post(
        "/v1/scripts",
        json={"title": "", "idea": "深夜便利店的秘密"},
        headers=auth_header(author),
    )
    episode_id = next(data for kind, data in _parse_sse(created.text) if kind == "complete")[
        "episode_id"
    ]

    db.add(EpisodeCut(episode_id=episode_id, name="正片"))
    db.flush()

    response = client.delete(f"/v1/scripts/{episode_id}", headers=auth_header(author))
    assert response.status_code == 422

    assert db.get(DramaEpisode, episode_id) is not None


def test_list_scripts_shows_zero_turn_shells_too(
    client: TestClient, db: Session, author: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`list_scripts` used to require a turn to exist — relaxed so a script
    whose first draft is still streaming (in another tab/device) or failed
    outright stays discoverable instead of vanishing until it either
    finishes or is manually retried (`retry_new_script`)."""
    from app.llm import client as llm_client

    _enable_script_studio(db, author)
    _patch_stream_session(monkeypatch, db)

    empty_list = client.get("/v1/scripts", headers=auth_header(author))
    assert empty_list.status_code == 200
    assert empty_list.json() == []

    def empty_stream(**kwargs: Any) -> Any:
        kwargs["result"].text = ""
        yield from ()

    monkeypatch.setattr(llm_client, "stream_complete", empty_stream)
    client.post(
        "/v1/scripts",
        json={"title": "", "idea": "深夜便利店的秘密"},
        headers=auth_header(author),
    )

    zero_turn = client.get("/v1/scripts", headers=auth_header(author))
    assert len(zero_turn.json()) == 1
    assert zero_turn.json()[0]["turn_count"] == 0

    from tests.fake_llm_gateway import fake_stream_complete

    monkeypatch.setattr(llm_client, "stream_complete", fake_stream_complete)
    client.post(
        "/v1/scripts",
        json={"title": "", "idea": "另一个故事"},
        headers=auth_header(author),
    )

    populated = client.get("/v1/scripts", headers=auth_header(author))
    assert len(populated.json()) == 2
    assert sorted(row["turn_count"] for row in populated.json()) == [0, 1]
