"""`POST /v1/generation/prompts/enhance`: the generation studio's own polish
endpoint. `ShortformStudio` used to have its own copy behind the
`shortform_studio` feature flag (`POST /v1/shortform/prompt/enhance`); that
route was removed along with the rest of that studio, so this endpoint is the
only one left and it carries no feature-flag gate of its own."""

from __future__ import annotations

import json
from contextlib import contextmanager
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents import copywriter
from app.api.v1 import prompts as prompts_api
from app.domain import prompts
from app.domain.agent_skills import service as agent_skills_service
from app.llm import client as llm_client
from app.models import AgentRun, User
from tests.conftest import auth_header
from tests.llm_catalog import bind_default_agents_to_catalog


def _patch_stream_session(monkeypatch: pytest.MonkeyPatch, db: Session) -> None:
    """Streaming finalize opens `session_scope()` after the request session
    closes. Tests share one rolled-back transaction, so point that factory
    at the fixture session (same as `test_scripts._patch_stream_session`)."""

    @contextmanager
    def fake_session_scope():
        yield db

    monkeypatch.setattr(prompts_api, "session_scope", fake_session_scope)


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


def _enhance_complete(response) -> dict[str, Any]:
    return next(data for kind, data in _parse_sse(response.text) if kind == "complete")


@pytest.fixture
def bound_copy_agent(db: Session) -> None:
    """A catalog the copy agent can actually run on.

    Without it every call degrades, which these tests would rather assert
    explicitly (see `test_enhance_reports_an_outage_instead_of_echoing_back`)
    than accidentally exercise everywhere.
    """
    bind_default_agents_to_catalog(db)
    db.commit()


def test_enhance_diagnoses_each_dimension(
    client: TestClient,
    db: Session,
    author: User,
    bound_copy_agent: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_stream_session(monkeypatch, db)
    response = client.post(
        "/v1/generation/prompts/enhance",
        json={"prompt": "女孩在海边", "operation": "text_to_video", "duration_seconds": 8},
        headers=auth_header(author),
    )
    assert response.status_code == 200, response.text
    kinds = [kind for kind, _ in _parse_sse(response.text)]
    assert "thinking" in kinds
    body = _enhance_complete(response)
    assert body["detail_level"] in ("sparse", "adequate", "detailed")
    assert body["prompt"]
    assert body["feedback"]
    assert {d["key"] for d in body["dimensions"]} == {
        "subject",
        "scene",
        "action",
        "camera",
        "lighting",
        "mood",
        "pacing",
    }
    assert all(d["status"] in ("missing", "weak", "ok") for d in body["dimensions"])
    assert body["additions"]


def test_enhance_video_asset_kind_general_uses_video_dimensions(
    client: TestClient,
    db: Session,
    author: User,
    bound_copy_agent: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Video studio sends `video_asset_kind` (not `asset_kind`). `general`
    still lands on the copy request bucket and the video dimension set."""
    _patch_stream_session(monkeypatch, db)
    response = client.post(
        "/v1/generation/prompts/enhance",
        json={
            "prompt": "女孩在海边转身",
            "operation": "text_to_video",
            "duration_seconds": 8,
            "video_asset_kind": "general",
        },
        headers=auth_header(author),
    )
    assert response.status_code == 200, response.text
    body = _enhance_complete(response)
    assert {d["key"] for d in body["dimensions"]} == {
        "subject",
        "scene",
        "action",
        "camera",
        "lighting",
        "mood",
        "pacing",
    }
    assert "complete" in [kind for kind, _ in _parse_sse(response.text)]


def test_enhance_diagnoses_image_prompts_on_image_dimensions(
    client: TestClient,
    db: Session,
    author: User,
    bound_copy_agent: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No camera or pacing advice on a still image — the operation decides."""
    _patch_stream_session(monkeypatch, db)
    response = client.post(
        "/v1/generation/prompts/enhance",
        json={"prompt": "女孩在海边", "operation": "text_to_image"},
        headers=auth_header(author),
    )
    assert response.status_code == 200, response.text
    keys = {d["key"] for d in _enhance_complete(response)["dimensions"]}
    assert "composition" in keys
    assert "camera" not in keys
    assert "pacing" not in keys


def test_enhance_character_stream_completes_on_the_dedicated_agent(
    client: TestClient,
    db: Session,
    author: User,
    bound_copy_agent: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The studio's character button is this same SSE route with
    `asset_kind=character` — fake content is valid JSON, so this asserts the
    dedicated-agent hop plus the new finish path still emit `complete`."""
    _patch_stream_session(monkeypatch, db)
    specific = agent_skills_service.create_profile(
        db,
        role="copy",
        key="enhance-character-http",
        display_name="角色润色 · HTTP",
        default_for_asset_kind="character",
    )
    response = client.post(
        "/v1/generation/prompts/enhance",
        json={"prompt": "女孩在海边", "operation": "text_to_image", "asset_kind": "character"},
        headers=auth_header(author),
    )
    assert response.status_code == 200, response.text
    body = _enhance_complete(response)
    assert body["prompt"]
    run = db.scalars(select(AgentRun).order_by(AgentRun.created_at.desc())).first()
    assert run is not None
    assert run.agent_profile_id == specific.id
    assert run.degraded is False


@pytest.mark.real_gateway_seams
def test_enhance_stream_reports_unavailable_when_thinking_never_becomes_json(
    client: TestClient,
    db: Session,
    author: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The live failure mode: thinking deltas arrive, then `event: error`
    with the product copy — not a silent echo of the author's own prompt."""
    bind_default_agents_to_catalog(db)
    db.commit()
    _patch_stream_session(monkeypatch, db)

    def _stream_gateway(**_kwargs):  # type: ignore[no-untyped-def]
        yield llm_client.StreamDelta(reasoning="先分析这段描述缺什么", finish_reason="length")

    monkeypatch.setattr(llm_client, "_stream_gateway", _stream_gateway)
    response = client.post(
        "/v1/generation/prompts/enhance",
        json={"prompt": "女孩在海边", "operation": "text_to_image", "asset_kind": "character"},
        headers=auth_header(author),
    )
    assert response.status_code == 200, response.text
    events = _parse_sse(response.text)
    kinds = [kind for kind, _ in events]
    assert "thinking" in kinds
    assert "complete" not in kinds
    error = next(data for kind, data in events if kind == "error")
    assert error["message"] == prompts.ENHANCE_UNAVAILABLE_MESSAGE
    run = db.scalars(select(AgentRun).order_by(AgentRun.created_at.desc())).first()
    assert run is not None
    assert run.degraded is True
    assert run.degrade_reason == "json_parse_failed"


@pytest.mark.real_gateway_seams
def test_enhance_reports_an_outage_instead_of_echoing_back(
    client: TestClient, author: User
) -> None:
    """No catalog bound, so the call must fail loudly.

    Echoing the author's own text back as a "polish" is what made this
    feature look broken before; a 503 is the honest answer. Opts out of the
    autouse fake gateway (`@pytest.mark.real_gateway_seams`) since the fake
    stays permissive about unbound models — this needs the real
    `app.llm.client.complete` to observe the actual production rule.
    """
    response = client.post(
        "/v1/generation/prompts/enhance",
        json={"prompt": "女孩在海边"},
        headers=auth_header(author),
    )
    assert response.status_code == 503, response.text
    assert response.json()["error"]["code"] == "PROVIDER_TEMPORARY_FAILURE"


def test_enhance_returns_script_segment_in_place(
    client: TestClient,
    db: Session,
    author: User,
    bound_copy_agent: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_stream_session(monkeypatch, db)
    response = client.post(
        "/v1/generation/prompts/enhance",
        json={
            "prompt": "雨巷\n苏晴撑伞停下",
            "operation": "text_to_video",
            "script_segment": {
                "heading": "雨巷",
                "blocks": [
                    {"type": "action", "character": None, "text": "苏晴撑伞停下"},
                    {"type": "dialogue", "character": "苏晴", "text": "你终于来了。"},
                ],
            },
        },
        headers=auth_header(author),
    )
    assert response.status_code == 200, response.text
    body = _enhance_complete(response)
    assert body["script_segment"]["heading"] == "雨巷"
    assert [block["type"] for block in body["script_segment"]["blocks"]] == ["action", "dialogue"]
    assert body["script_segment"]["blocks"][1]["character"] == "苏晴"
    assert body["script_segment"]["blocks"][0]["text"] != "苏晴撑伞停下"


def test_enhance_requires_login(client: TestClient) -> None:
    response = client.post("/v1/generation/prompts/enhance", json={"prompt": "女孩在海边"})
    assert response.status_code == 401


def test_scene_enhance_asks_follow_ups_then_stops_once_they_are_answered(
    client: TestClient,
    db: Session,
    author: User,
    bound_copy_agent: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The scene plate's whole point: the studio can block submission on a
    required answer, and answering must clear the block rather than loop."""
    _patch_stream_session(monkeypatch, db)
    payload = {
        "prompt": "夜晚老旧出租屋门口，紧闭的旧式铁框防盗门，门后是走廊与厨房",
        "operation": "text_to_image",
        "asset_kind": "scene",
    }
    first = client.post(
        "/v1/generation/prompts/enhance", json=payload, headers=auth_header(author)
    )
    assert first.status_code == 200, first.text
    asked = _enhance_complete(first)["questions"]
    assert [question["id"] for question in asked] == ["space_type", "anchor"]
    assert all(question["required"] for question in asked)
    space_type = next(q for q in asked if q["id"] == "space_type")
    assert any(option["value"] == "corridor_stairwell" for option in space_type["options"])

    answered = client.post(
        "/v1/generation/prompts/enhance",
        json={
            **payload,
            "question_answers": {"space_type": "corridor_stairwell", "anchor": "1990s_china_south"},
        },
        headers=auth_header(author),
    )
    assert answered.status_code == 200, answered.text
    assert _enhance_complete(answered)["questions"] == []


def test_scene_enhance_locks_the_medium_and_the_occlusion(
    client: TestClient,
    db: Session,
    author: User,
    bound_copy_agent: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The seatbelt runs on the real response, not just in unit tests: a
    closed door with a kitchen behind it comes back with the occlusion rule
    pinned on, and a plate that named no medium comes back locked to one."""
    _patch_stream_session(monkeypatch, db)
    response = client.post(
        "/v1/generation/prompts/enhance",
        json={
            "prompt": "夜晚老旧出租屋门口，紧闭的旧式铁框防盗门，门后走廊尽头的厨房堆着待洗的碗碟",
            "operation": "text_to_image",
            "asset_kind": "scene",
        },
        headers=auth_header(author),
    )
    assert response.status_code == 200, response.text
    enhanced = _enhance_complete(response)["prompt"]
    assert copywriter.SCENE_PLATE_OCCLUSION_SENTENCE in enhanced
    assert copywriter.SCENE_PLATE_MEDIUM_SENTENCE in enhanced


def test_a_non_scene_polish_never_asks(
    client: TestClient,
    db: Session,
    author: User,
    bound_copy_agent: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only the scene coach asks today — a cover polish must not start
    blocking the studio's submit button."""
    _patch_stream_session(monkeypatch, db)
    response = client.post(
        "/v1/generation/prompts/enhance",
        json={"prompt": "一张短剧封面", "operation": "text_to_image", "asset_kind": "cover"},
        headers=auth_header(author),
    )
    assert response.status_code == 200, response.text
    assert _enhance_complete(response)["questions"] == []
