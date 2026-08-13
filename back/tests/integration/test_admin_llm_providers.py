"""Admin `/llm-providers`: endpoint-level primary/backup demotion and secret
redaction."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditLog, User
from app.providers.connectivity import ConnectivityResult
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
        "max_concurrency": 4,
        "timeout_ms": 30_000,
        "enabled": True,
    }
    payload.update(overrides)
    return payload


def _media_payload(
    *,
    model: str = "m1",
    input_modalities: list[str],
    output_modalities: list[str],
    **overrides: object,
) -> dict:
    payload = {
        "name": "AiHubMix",
        "base_url": "https://aihubmix.invalid",
        "api_key": "sk-media",
        "kind": "media",
        "models": [],
        "role": "backup",
        "backup_order": 100,
        "model": model,
        "input_modalities": input_modalities,
        "output_modalities": output_modalities,
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


def test_media_endpoints_have_no_primary_or_concurrency_semantics(
    client: TestClient, admin: User
) -> None:
    _upsert(client, admin, "ep-general", _general_payload(role="primary"))
    _upsert(
        client,
        admin,
        "ep-a",
        _media_payload(
            model="m1",
            input_modalities=["text"],
            output_modalities=["image", "audio"],
            role="primary",
        ),
    )
    body = _upsert(
        client,
        admin,
        "ep-b",
        _media_payload(
            model="m2",
            input_modalities=["text"],
            output_modalities=["image"],
            role="primary",
        ),
    )

    assert body["demoted_endpoint_ids"] == []
    by_id = {e["id"]: e for e in body["endpoints"]}
    assert by_id["ep-a"]["role"] == "backup"
    assert by_id["ep-b"]["role"] == "backup"
    assert by_id["ep-b"]["max_concurrency"] == 1
    assert by_id["ep-general"]["role"] == "primary"
    assert set(by_id["ep-a"]["capabilities"]) == {"text_to_image", "audio_generation"}
    assert by_id["ep-b"]["capabilities"] == ["text_to_image"]


def test_media_requires_a_modality_combination_that_derives_a_capability(
    client: TestClient, admin: User
) -> None:
    """`video` input + `audio` output covers no `Operation`, so it must be
    rejected rather than silently saved with zero servable capabilities."""
    response = client.put(
        "/v1/admin/llm-providers/ep-bad",
        json=_media_payload(model="m1", input_modalities=["video"], output_modalities=["audio"]),
        headers=admin_header(admin),
    )
    assert response.status_code == 422


def test_media_requires_a_model_name(client: TestClient, admin: User) -> None:
    response = client.put(
        "/v1/admin/llm-providers/ep-bad",
        json=_media_payload(model="", input_modalities=["text"], output_modalities=["image"]),
        headers=admin_header(admin),
    )
    assert response.status_code == 422


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


def test_admin_can_validate_one_exact_endpoint_and_the_result_is_audited(
    client: TestClient,
    admin: User,
    db: Session,
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    _upsert(client, admin, "ep-validate", _general_payload(api_key="sk-never-return-this"))
    seen: list[str] = []

    def fake_validate(endpoint):  # type: ignore[no-untyped-def]
        seen.append(endpoint.base_url)
        return ConnectivityResult(
            target_model="kimi-k3",
            probe_type="chat_completion",
            reachable=True,
            usable=True,
            latency_ms=17,
            provider_status_code=200,
            provider_error_code=None,
            provider_error_message=None,
            external_task_id="task-validation-1",
        )

    monkeypatch.setattr(
        "app.api.v1.admin.llm_providers.connectivity.validate_endpoint", fake_validate
    )
    response = client.post(
        "/v1/admin/llm-providers/ep-validate/validate", headers=admin_header(admin)
    )

    assert response.status_code == 200
    assert seen == ["https://gateway.invalid/v1"]
    body = response.json()
    assert body["usable"] is True
    assert body["target_model"] == "kimi-k3"
    assert body["external_task_id"] == "task-validation-1"
    assert "sk-never-return-this" not in response.text

    entry = db.scalar(
        select(AuditLog).where(
            AuditLog.action == "llm_provider.validate",
            AuditLog.target_id == "ep-validate",
        )
    )
    assert entry is not None
    assert entry.after_json["usable"] is True
    assert entry.after_json["external_task_id"] == "task-validation-1"
    assert "api_key" not in str(entry.after_json)


def test_non_admin_cannot_validate_an_endpoint(
    client: TestClient, admin: User, reviewer: User
) -> None:
    _upsert(client, admin, "ep-protected", _general_payload())
    response = client.post(
        "/v1/admin/llm-providers/ep-protected/validate", headers=admin_header(reviewer)
    )
    assert response.status_code == 403


def test_validating_a_missing_endpoint_returns_not_found(client: TestClient, admin: User) -> None:
    response = client.post("/v1/admin/llm-providers/missing/validate", headers=admin_header(admin))
    assert response.status_code == 404


def test_media_upsert_infers_protocol_when_omitted(
    client: TestClient, admin: User, db: Session
) -> None:
    body = _upsert(
        client,
        admin,
        "ep-image",
        _media_payload(model="gpt-image-1", input_modalities=["text"], output_modalities=["image"]),
    )
    endpoint = next(item for item in body["endpoints"] if item["id"] == "ep-image")
    assert endpoint["protocol"] == "openai"
    entry = db.scalar(
        select(AuditLog).where(
            AuditLog.action == "llm_provider.upsert",
            AuditLog.target_id == "ep-image",
        )
    )
    assert entry is not None
    assert entry.after_json["protocol"] == "openai"


def test_media_upsert_persists_an_explicit_protocol(client: TestClient, admin: User) -> None:
    body = _upsert(
        client,
        admin,
        "ep-video",
        _media_payload(
            model="minimax-h3",
            input_modalities=["text"],
            output_modalities=["video"],
            protocol="minimax",
        ),
    )
    endpoint = next(item for item in body["endpoints"] if item["id"] == "ep-video")
    assert endpoint["protocol"] == "minimax"


def test_unimplemented_media_protocol_is_rejected(client: TestClient, admin: User) -> None:
    for protocol in ("comfyui", "google"):
        response = client.put(
            "/v1/admin/llm-providers/ep-future",
            json=_media_payload(
                model="future",
                input_modalities=["text"],
                output_modalities=["image"],
                protocol=protocol,
            ),
            headers=admin_header(admin),
        )
        assert response.status_code == 422, protocol


def test_protocol_must_match_modalities(client: TestClient, admin: User) -> None:
    openai_video = client.put(
        "/v1/admin/llm-providers/ep-bad",
        json=_media_payload(
            model="gpt-image-1",
            input_modalities=["text"],
            output_modalities=["video"],
            protocol="openai",
        ),
        headers=admin_header(admin),
    )
    assert openai_video.status_code == 422

    minimax_image = client.put(
        "/v1/admin/llm-providers/ep-bad",
        json=_media_payload(
            model="minimax-h3",
            input_modalities=["text"],
            output_modalities=["image"],
            protocol="minimax",
        ),
        headers=admin_header(admin),
    )
    assert minimax_image.status_code == 422
