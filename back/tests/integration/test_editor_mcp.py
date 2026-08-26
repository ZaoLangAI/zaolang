"""MCP audience isolation and tool ACL."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import User
from app.platform_config import service as config_service
from app.platform_config.schemas import FeatureFlags
from app.security.tokens import issue_consumer_tokens
from tests.conftest import auth_header, make_user
from tests.integration.test_editor import _video_asset


def _enable(session: Session, admin: User) -> None:
    value = config_service.get_typed(session, "feature_flags", FeatureFlags).model_dump(mode="json")
    value.update(
        {
            "drama_studio_enabled": True,
            "web_editor_enabled": True,
            "editor_mcp_enabled": True,
        }
    )
    config_service.set_value(session, "feature_flags", value, actor_user_id=admin.id, note="test")


def test_a_consumer_token_is_rejected_by_mcp(
    client: TestClient, db: Session, author: User, admin: User
) -> None:
    _enable(db, admin)
    token, _, _ = issue_consumer_tokens(author.id, list(author.roles))
    response = client.post(
        "/mcp",
        headers={"Authorization": f"Bearer {token}"},
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
    )
    assert response.status_code == 401
    assert response.json()["error"]["message"] == "UNAUTHENTICATED"


def test_mcp_token_is_scoped_to_one_project(
    client: TestClient, db: Session, author: User, admin: User
) -> None:
    _enable(db, admin)
    series = client.post("/v1/drama-series", headers=auth_header(author), json={"title": "MCP剧"})
    assert series.status_code == 201, series.text
    minted = client.post(
        "/v1/mcp/tokens",
        headers=auth_header(author),
        json={
            "series_id": series.json()["id"],
            "client_id": "cursor",
            "scopes": ["drama:read", "editor:read"],
        },
    )
    assert minted.status_code == 201, minted.text
    other = client.post(
        "/v1/drama-series", headers=auth_header(author), json={"title": "另一部"}
    ).json()
    call = client.post(
        "/mcp",
        headers={"Authorization": f"Bearer {minted.json()['access_token']}"},
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "drama.list_series",
                "arguments": {"project_id": other["id"]},
            },
        },
    )
    assert call.status_code == 403
    assert call.json()["error"]["message"] == "PROJECT_FORBIDDEN"


def test_request_transcription_tool_enqueues_for_an_owned_asset(
    client: TestClient, db: Session, author: User, admin: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AI-triggerable, but this tool only ever produces a draft transcript —
    there is no MCP tool anywhere in this surface that turns it into real
    caption elements without a human reviewing it first."""
    _enable(db, admin)
    asset = _video_asset(db, author)
    db.commit()

    seen: list[str] = []
    monkeypatch.setattr(
        "app.mcp.server.celery_app.send_task",
        lambda name, args=None, **kwargs: seen.append((args or [""])[0]),
    )

    series = client.post("/v1/drama-series", headers=auth_header(author), json={"title": "转写测试"})
    assert series.status_code == 201, series.text
    minted = client.post(
        "/v1/mcp/tokens",
        headers=auth_header(author),
        json={
            "series_id": series.json()["id"],
            "client_id": "cursor",
            "scopes": ["editor:write", "editor:read"],
        },
    )
    assert minted.status_code == 201, minted.text

    call = client.post(
        "/mcp",
        headers={"Authorization": f"Bearer {minted.json()['access_token']}"},
        json={
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "editor.request_transcription",
                "arguments": {"project_id": series.json()["id"], "asset_id": asset.id},
            },
        },
    )
    assert call.status_code == 200, call.text
    payload = json.loads(call.json()["result"]["content"][0]["text"])
    assert payload["kind"] == "media_analysis"
    assert payload["id"].startswith("man_")
    assert seen == [payload["id"]]

    # A second call for the same asset returns the same row rather than
    # queuing a duplicate transcription.
    again = client.post(
        "/mcp",
        headers={"Authorization": f"Bearer {minted.json()['access_token']}"},
        json={
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "editor.request_transcription",
                "arguments": {"project_id": series.json()["id"], "asset_id": asset.id},
            },
        },
    )
    again_payload = json.loads(again.json()["result"]["content"][0]["text"])
    assert again_payload["id"] == payload["id"]


def test_request_transcription_tool_rejects_someone_elses_asset(
    client: TestClient, db: Session, author: User, admin: User
) -> None:
    other_owner = make_user(db, email="mcp-not-owner@example.com", handle="mcpnotowner")
    _enable(db, admin)
    asset = _video_asset(db, other_owner)
    db.commit()

    series = client.post("/v1/drama-series", headers=auth_header(author), json={"title": "转写越权测试"})
    assert series.status_code == 201, series.text
    minted = client.post(
        "/v1/mcp/tokens",
        headers=auth_header(author),
        json={
            "series_id": series.json()["id"],
            "client_id": "cursor",
            "scopes": ["editor:write"],
        },
    )
    assert minted.status_code == 201, minted.text

    call = client.post(
        "/mcp",
        headers={"Authorization": f"Bearer {minted.json()['access_token']}"},
        json={
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {
                "name": "editor.request_transcription",
                "arguments": {"project_id": series.json()["id"], "asset_id": asset.id},
            },
        },
    )
    assert call.status_code == 422
    assert call.json()["error"]["message"] == "VALIDATION_FAILED"
