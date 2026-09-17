"""`GET /v1/scripts/{episode_id}` carries the deterministic lint findings."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import DramaEpisode, User
from tests.conftest import auth_header
from tests.integration.test_scripts import (
    _enable_script_studio,
    _parse_sse,
    _patch_stream_session,
)


def test_script_detail_lists_lint_findings_with_skill_suggestions(
    client: TestClient, db: Session, author: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_script_studio(db, author)
    _patch_stream_session(monkeypatch, db)
    created = client.post(
        "/v1/scripts", json={"title": "", "idea": "天台上的对峙"}, headers=auth_header(author)
    )
    assert created.status_code == 202
    episode_id = next(data for kind, data in _parse_sse(created.text) if kind == "complete")[
        "episode_id"
    ]

    episode = db.get(DramaEpisode, episode_id)
    assert episode is not None
    episode.script_json = {
        "title": "对峙",
        "logline": "",
        "characters": [{"name": "林夏", "traits": ""}],
        "scenes": [
            {
                "heading": "日·天台",
                "blocks": [
                    {"type": "scene", "text": "林夏站在天台边，逆光", "character": None},
                    {"type": "action", "text": "他很紧张地看着远处", "character": None},
                    {"type": "camera", "text": "镜头缓缓移动", "character": None},
                ],
            }
        ],
    }
    db.flush()

    detail = client.get(f"/v1/scripts/{episode_id}", headers=auth_header(author))
    assert detail.status_code == 200, detail.text
    lint = detail.json()["lint"]
    codes = {issue["code"] for issue in lint}
    assert {"person_in_scene_block", "emotion_label", "camera_directionless_move"} <= codes

    camera = next(issue for issue in lint if issue["code"] == "camera_directionless_move")
    assert camera["scene_index"] == 0
    assert camera["block_index"] == 2
    assert camera["dimension"] == "camera"
    assert 0 < len(camera["suggested_skills"]) <= 2
