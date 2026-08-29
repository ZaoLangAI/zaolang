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
        "model": "test-llm",
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


def test_a_general_endpoint_round_trips_its_context_limits_and_token_prices(
    client: TestClient, admin: User
) -> None:
    body = _upsert(
        client,
        admin,
        "ep-priced",
        _general_payload(
            context_length=128_000,
            max_output_tokens=16_384,
            token_pricing={
                "input_per_million_micro_usd": 60_000,
                "output_per_million_micro_usd": 220_000,
            },
        ),
    )

    endpoint = body["endpoints"][0]
    assert endpoint["context_length"] == 128_000
    assert endpoint["max_output_tokens"] == 16_384
    assert endpoint["token_pricing"]["input_per_million_micro_usd"] == 60_000
    assert endpoint["token_pricing"]["output_per_million_micro_usd"] == 220_000


def test_a_general_endpoint_can_declare_video_input_support(
    client: TestClient, admin: User, db: Session
) -> None:
    """Text is auto-injected, video makes the endpoint a `video_analysis`
    candidate, and the audit log records the real value rather than the
    hardcoded `[]` a general endpoint used to get."""
    body = _upsert(
        client,
        admin,
        "ep-video-general",
        _general_payload(input_modalities=["video"]),
    )

    endpoint = body["endpoints"][0]
    assert sorted(endpoint["input_modalities"]) == ["text", "video"]
    assert endpoint["output_modalities"] == []
    assert endpoint["capabilities"] == ["video_analysis"]

    entry = db.scalar(
        select(AuditLog).where(
            AuditLog.action == "llm_provider.upsert",
            AuditLog.target_id == "ep-video-general",
        )
    )
    assert entry is not None
    assert sorted(entry.after_json["input_modalities"]) == ["text", "video"]


def test_a_general_endpoint_without_video_has_no_capabilities(
    client: TestClient, admin: User
) -> None:
    body = _upsert(client, admin, "ep-plain-general", _general_payload())
    endpoint = body["endpoints"][0]
    assert endpoint["input_modalities"] == ["text"]
    assert endpoint["capabilities"] == []


def test_a_general_endpoint_rejects_an_unsupported_input_modality(
    client: TestClient, admin: User
) -> None:
    response = client.put(
        "/v1/admin/llm-providers/ep-bad-general",
        json=_general_payload(input_modalities=["audio"]),
        headers=admin_header(admin),
    )
    assert response.status_code == 422


def test_a_media_endpoint_keeps_only_the_prices_its_capabilities_can_bill(
    client: TestClient, admin: User
) -> None:
    """The console submits all three sections; the server is what decides
    which ones this endpoint can actually charge against."""
    body = _upsert(
        client,
        admin,
        "ep-image-priced",
        _media_payload(
            model="gpt-image-1",
            input_modalities=["text"],
            output_modalities=["image"],
            media_pricing={
                "image": {
                    "input_per_image_micro_usd": 2_860,
                    "generation_per_image_micro_usd": 25_350,
                },
                "audio": {"per_10k_characters_micro_usd": 141_000},
                "video": {"generation_per_second_micro_usd": {"2K": 123_970}},
            },
        ),
    )

    pricing = body["endpoints"][0]["media_pricing"]
    assert pricing["image"]["generation_per_image_micro_usd"] == 25_350
    assert pricing["audio"] is None
    assert pricing["video"] is None


def test_an_unsupported_video_resolution_is_rejected(client: TestClient, admin: User) -> None:
    response = client.put(
        "/v1/admin/llm-providers/ep-bad-resolution",
        json=_media_payload(
            model="video-1",
            input_modalities=["text"],
            output_modalities=["video"],
            media_pricing={"video": {"generation_per_second_micro_usd": {"4K": 123_970}}},
        ),
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
            target_model="test-llm",
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
    body = response.json()
    assert body["status"] == "running"
    assert body["result"] is None
    assert body["validation_id"].startswith("val_")
    assert "sk-never-return-this" not in response.text
    assert seen == ["https://gateway.invalid/v1"]

    polled = client.get(
        f"/v1/admin/llm-providers/ep-validate/validate/{body['validation_id']}",
        headers=admin_header(admin),
    )
    assert polled.status_code == 200
    result = polled.json()
    assert result["status"] == "completed"
    assert result["result"]["usable"] is True
    assert result["result"]["target_model"] == "test-llm"
    assert result["result"]["external_task_id"] == "task-validation-1"
    assert "sk-never-return-this" not in polled.text

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


def test_a_viewer_can_poll_a_validation_job(
    client: TestClient, admin: User, db: Session, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    from app.models.enums import UserRole
    from tests.conftest import make_user

    viewer = make_user(
        db,
        email="viewer-validate@example.com",
        handle="viewer-validate",
        display_name="观察者",
        roles=[UserRole.USER.value, UserRole.VIEWER.value],
    )
    _upsert(client, admin, "ep-poll", _general_payload())
    monkeypatch.setattr(
        "app.api.v1.admin.llm_providers.connectivity.validate_endpoint",
        lambda endpoint: ConnectivityResult(  # type: ignore[misc]
            target_model="test-llm",
            probe_type="chat_completion",
            reachable=True,
            usable=True,
            latency_ms=9,
        ),
    )
    started = client.post(
        "/v1/admin/llm-providers/ep-poll/validate", headers=admin_header(admin)
    )
    assert started.status_code == 200
    validation_id = started.json()["validation_id"]
    polled = client.get(
        f"/v1/admin/llm-providers/ep-poll/validate/{validation_id}",
        headers=admin_header(viewer),
    )
    assert polled.status_code == 200
    assert polled.json()["status"] == "completed"


def test_polling_an_unknown_validation_returns_not_found(client: TestClient, admin: User) -> None:
    response = client.get(
        "/v1/admin/llm-providers/ep-missing/validate/val_doesnotexist",
        headers=admin_header(admin),
    )
    assert response.status_code == 404


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


def test_openai_protocol_now_accepts_video_via_the_openai_videos_api(
    client: TestClient, admin: User
) -> None:
    """`openai`+video used to 422 — the OpenAI Videos API track
    (`/v1/videos` create/retrieve/download_content) made this a legal
    combination. `minimax`+image/audio (below) is the combination that still
    doesn't make sense and still 422s."""
    body = _upsert(
        client,
        admin,
        "ep-openai-video",
        _media_payload(
            model="wan2.7-videoedit",
            input_modalities=["text"],
            output_modalities=["video"],
            protocol="openai",
        ),
    )
    endpoint = next(item for item in body["endpoints"] if item["id"] == "ep-openai-video")
    assert endpoint["protocol"] == "openai"


def test_protocol_must_match_modalities(client: TestClient, admin: User) -> None:
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
