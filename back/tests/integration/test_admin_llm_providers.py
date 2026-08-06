"""Admin `/llm-providers`: endpoint-level primary/backup demotion and secret
redaction."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.models import User
from tests.conftest import admin_header


def _upsert(client: TestClient, admin: User, endpoint_id: str, payload: dict) -> dict:
    response = client.put(
        f"/v1/admin/llm-providers/{endpoint_id}", json=payload, headers=admin_header(admin)
    )
    assert response.status_code == 200, response.text
    return response.json()


def _general_payload(**overrides: object) -> dict:
    payload = {
        "name": "通用网关",
        "base_url": "https://gateway.invalid/v1",
        "api_key": "sk-test",
        "kind": "general",
        "models": ["kimi-k3"],
        "role": "backup",
        "backup_order": 100,
        "capabilities": {},
        "max_concurrency": 4,
        "timeout_ms": 30_000,
        "enabled": True,
    }
    payload.update(overrides)
    return payload


def _media_payload(capabilities: dict, **overrides: object) -> dict:
    payload = {
        "name": "AiHubMix",
        "base_url": "https://aihubmix.invalid",
        "api_key": "sk-media",
        "kind": "media",
        "models": [],
        "role": "backup",
        "backup_order": 100,
        "capabilities": capabilities,
        "max_concurrency": 4,
        "timeout_ms": 30_000,
        "enabled": True,
    }
    payload.update(overrides)
    return payload


def test_the_pool_lists_a_flat_endpoint_list(client: TestClient, admin: User) -> None:
    body = _upsert(client, admin, "ep-general", _general_payload(role="primary"))
    assert body["categories"] == []
    assert len(body["endpoints"]) == 1
    endpoint = body["endpoints"][0]
    assert endpoint["id"] == "ep-general"
    assert endpoint["kind"] == "general"
    assert endpoint["role"] == "primary"


def test_a_new_general_primary_demotes_the_previous_one(client: TestClient, admin: User) -> None:
    _upsert(client, admin, "ep-a", _general_payload(role="primary"))
    body = _upsert(client, admin, "ep-b", _general_payload(role="primary"))

    assert body["demoted_endpoint_ids"] == ["ep-a"]
    by_id = {e["id"]: e for e in body["endpoints"]}
    assert by_id["ep-a"]["role"] == "backup"
    assert by_id["ep-b"]["role"] == "primary"


def test_media_primary_demotes_other_media_not_general(client: TestClient, admin: User) -> None:
    _upsert(client, admin, "ep-general", _general_payload(role="primary"))
    _upsert(
        client,
        admin,
        "ep-a",
        _media_payload(
            {
                "text_to_image": {"model": "m1", "enabled": True},
                "audio_generation": {"model": "tts-a", "enabled": True},
            },
            role="primary",
        ),
    )
    body = _upsert(
        client,
        admin,
        "ep-b",
        _media_payload(
            {"text_to_image": {"model": "m2", "enabled": True}},
            role="primary",
        ),
    )

    assert body["demoted_endpoint_ids"] == ["ep-a"]
    by_id = {e["id"]: e for e in body["endpoints"]}
    assert by_id["ep-a"]["role"] == "backup"
    assert by_id["ep-b"]["role"] == "primary"
    assert by_id["ep-general"]["role"] == "primary"
    assert set(by_id["ep-a"]["capabilities"]) == {"text_to_image", "audio_generation"}
    assert "role" not in by_id["ep-b"]["capabilities"]["text_to_image"]


def test_api_key_is_never_echoed_back(client: TestClient, admin: User) -> None:
    body = _upsert(client, admin, "ep-secret", _general_payload(api_key="sk-super-secret"))
    endpoint = body["endpoints"][0]
    assert "sk-super-secret" not in str(endpoint)
    assert endpoint["api_key_configured"] is True


def test_removing_an_endpoint_requires_confirmation(client: TestClient, admin: User) -> None:
    _upsert(client, admin, "ep-remove", _general_payload())
    response = client.post(
        "/v1/admin/llm-providers/ep-remove/remove",
        json={"confirm": False, "reason": "清理测试端点"},
        headers=admin_header(admin),
    )
    assert response.status_code == 422

    response = client.post(
        "/v1/admin/llm-providers/ep-remove/remove",
        json={"confirm": True, "reason": "清理测试端点"},
        headers=admin_header(admin),
    )
    assert response.status_code == 200
    assert all(e["id"] != "ep-remove" for e in response.json()["endpoints"])
