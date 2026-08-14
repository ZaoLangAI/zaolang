"""MCP audience isolation and tool ACL."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import User
from app.platform_config import service as config_service
from app.platform_config.schemas import FeatureFlags
from app.security.tokens import issue_consumer_tokens
from tests.conftest import auth_header


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
