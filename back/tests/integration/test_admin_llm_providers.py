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
        "timeout_ms": 90_000 if "image" in output_modalities else 30_000,
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


def test_an_image_media_endpoint_rejects_a_sub_90s_timeout(
    client: TestClient, admin: User
) -> None:
    response = client.put(
        "/v1/admin/llm-providers/ep-short",
        json=_media_payload(
            model="m1",
            input_modalities=["text"],
            output_modalities=["image"],
            timeout_ms=30_000,
        ),
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
    assert endpoint["generation_kind"] == "create"


def test_media_upsert_persists_generation_kind(client: TestClient, admin: User) -> None:
    body = _upsert(
        client,
        admin,
        "ep-edit",
        _media_payload(
            model="wan2.7-videoedit",
            input_modalities=["text", "video"],
            output_modalities=["video"],
            protocol="minimax",
            generation_kind="edit",
        ),
    )
    endpoint = next(item for item in body["endpoints"] if item["id"] == "ep-edit")
    assert endpoint["generation_kind"] == "edit"


def test_media_upsert_defaults_audio_generation_kind_to_voice(
    client: TestClient, admin: User
) -> None:
    body = _upsert(
        client,
        admin,
        "ep-tts",
        _media_payload(
            model="tts-1",
            input_modalities=["text"],
            output_modalities=["audio"],
            protocol="dmxapi",
        ),
    )
    endpoint = next(item for item in body["endpoints"] if item["id"] == "ep-tts")
    assert endpoint["audio_generation_kind"] == "voice"
    assert endpoint["capabilities"] == ["audio_generation"]


def test_media_upsert_persists_audio_generation_kind_music_and_its_price(
    client: TestClient, admin: User
) -> None:
    body = _upsert(
        client,
        admin,
        "ep-music",
        _media_payload(
            model="music-3.0",
            input_modalities=["text"],
            output_modalities=["audio"],
            protocol="dmxapi",
            audio_generation_kind="music",
            media_pricing={"music": {"per_request_micro_usd": 120_000}},
        ),
    )
    endpoint = next(item for item in body["endpoints"] if item["id"] == "ep-music")
    assert endpoint["audio_generation_kind"] == "music"
    assert endpoint["capabilities"] == ["music_generation"]
    assert endpoint["media_pricing"]["music"]["per_request_micro_usd"] == 120_000
    # The same modality pair without `audio_generation_kind="music"` derives
    # `audio_generation`, not `music_generation` — proof the field, not the
    # modalities, is what breaks the tie.
    assert endpoint["media_pricing"].get("audio") is None


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


def test_dmxapi_protocol_endpoint_saves_with_its_own_video_capabilities(
    client: TestClient, admin: User
) -> None:
    body = _upsert(
        client,
        admin,
        "ep-dmxapi-video",
        _media_payload(
            model="MiniMax-H3",
            input_modalities=["text", "image", "video", "audio"],
            output_modalities=["video"],
            protocol="dmxapi",
        ),
    )
    endpoint = next(item for item in body["endpoints"] if item["id"] == "ep-dmxapi-video")
    assert endpoint["protocol"] == "dmxapi"
    assert set(endpoint["capabilities"]) == {"text_to_video", "image_to_video", "video_to_video"}


def test_fal_protocol_endpoint_saves_with_its_own_video_capabilities(
    client: TestClient, admin: User
) -> None:
    body = _upsert(
        client,
        admin,
        "ep-fal-video",
        _media_payload(
            model="minimax/h3-max",
            input_modalities=["text", "image", "video", "audio"],
            output_modalities=["video"],
            protocol="fal",
        ),
    )
    endpoint = next(item for item in body["endpoints"] if item["id"] == "ep-fal-video")
    assert endpoint["protocol"] == "fal"
    assert set(endpoint["capabilities"]) == {"text_to_video", "image_to_video", "video_to_video"}


def test_minimax_v2_protocol_endpoint_saves_with_its_own_video_capabilities(
    client: TestClient, admin: User
) -> None:
    body = _upsert(
        client,
        admin,
        "ep-metaso-video",
        _media_payload(
            model="MiniMax-H3",
            input_modalities=["text", "image", "video", "audio"],
            output_modalities=["video"],
            protocol="minimax_v2",
        ),
    )
    endpoint = next(item for item in body["endpoints"] if item["id"] == "ep-metaso-video")
    assert endpoint["protocol"] == "minimax_v2"
    assert set(endpoint["capabilities"]) == {"text_to_video", "image_to_video", "video_to_video"}


def test_the_model_catalog_lists_both_vendors_read_only(client: TestClient, admin: User) -> None:
    """`GET /llm-providers/catalog` is purely informational for the admin
    picker — it never touches `llm_providers` config."""
    response = client.get("/v1/admin/llm-providers/catalog", headers=admin_header(admin))
    assert response.status_code == 200
    body = response.json()
    vendors = {item["vendor"]: item for item in body["vendors"]}
    assert set(vendors) == {"aihubmix", "dmxapi", "metaso", "fal"}
    dmxapi_models = {entry["model"] for entry in vendors["dmxapi"]["models"]}
    assert "MiniMax-H3" in dmxapi_models
    assert "doubao-seedream-5-0-pro-260628" in dmxapi_models
    aihubmix_models = {entry["model"] for entry in vendors["aihubmix"]["models"]}
    assert "doubao-seedance-2-5-260628" in aihubmix_models
    assert "gpt-image-2" in aihubmix_models
    gpt_image_2 = next(
        entry for entry in vendors["aihubmix"]["models"] if entry["model"] == "gpt-image-2"
    )
    assert gpt_image_2["suggested_timeout_ms"] == 600_000
    assert gpt_image_2["protocol"] == "openai"
    metaso_h3 = next(
        entry for entry in vendors["metaso"]["models"] if entry["model"] == "MiniMax-H3"
    )
    assert metaso_h3["protocol"] == "minimax_v2"
    assert metaso_h3["billing_profile"] == "minimax_h3_payg"
    fal_h3_max = next(
        entry for entry in vendors["fal"]["models"] if entry["model"] == "minimax/h3-max"
    )
    assert fal_h3_max["protocol"] == "fal"
    assert fal_h3_max["billing_profile"] == "fal_h3_max"
    assert fal_h3_max["display_name"] == "MiniMax H3 Max"
    wan = next(
        entry for entry in vendors["aihubmix"]["models"] if entry["model"] == "wan2.7-videoedit"
    )
    assert wan["generation_kind"] == "edit"
    aihubmix_h3 = next(
        entry for entry in vendors["aihubmix"]["models"] if entry["model"] == "minimax-h3"
    )
    assert aihubmix_h3["generation_kind"] == "create"


def test_the_model_catalog_exposes_price_items_and_a_billing_profile(
    client: TestClient, admin: User
) -> None:
    """The admin picker needs each known model's own declared price items
    (with a default in micro-USD and the vendor page they were read from) to
    pre-fill pricing, not just protocol/modality metadata."""
    response = client.get("/v1/admin/llm-providers/catalog", headers=admin_header(admin))
    assert response.status_code == 200
    vendors = {item["vendor"]: item for item in response.json()["vendors"]}
    dmxapi_h3 = next(
        entry for entry in vendors["dmxapi"]["models"] if entry["model"] == "MiniMax-H3"
    )
    assert dmxapi_h3["billing_profile"] == "minimax_h3_payg"
    assert dmxapi_h3["pricing_doc_url"]
    assert dmxapi_h3["price_items"]
    two_k = next(
        item
        for item in dmxapi_h3["price_items"]
        if item["key"] == "video_generation" and item["dimension"] == "2K"
    )
    assert two_k["default_micro_usd"] > 0
    assert two_k["source_currency"] == "CNY"
    assert two_k["markup_note"]

    aihubmix_h3 = next(
        entry for entry in vendors["aihubmix"]["models"] if entry["model"] == "minimax-h3"
    )
    aihubmix_two_k = next(
        item
        for item in aihubmix_h3["price_items"]
        if item["key"] == "video_generation" and item["dimension"] == "2K"
    )
    # The regression the catalogue itself already guards in
    # `test_model_catalog.py`, re-asserted through the actual HTTP contract:
    # AiHubMix (USD), DMXAPI (CNY), and Metaso (its own H3 list) never share
    # one default for the same nominal upstream model.
    assert aihubmix_two_k["default_micro_usd"] != two_k["default_micro_usd"]
    metaso_h3 = next(
        entry for entry in vendors["metaso"]["models"] if entry["model"] == "MiniMax-H3"
    )
    metaso_two_k = next(
        item
        for item in metaso_h3["price_items"]
        if item["key"] == "video_generation" and item["dimension"] == "2K"
    )
    assert metaso_two_k["default_micro_usd"] != two_k["default_micro_usd"]
    assert metaso_two_k["default_micro_usd"] != aihubmix_two_k["default_micro_usd"]
    assert not metaso_two_k.get("markup_note")


def test_billing_profile_round_trips_through_upsert(client: TestClient, admin: User) -> None:
    body = _upsert(
        client,
        admin,
        "ep-seedance",
        _media_payload(
            model="doubao-seedance-2-5-260628",
            input_modalities=["text", "image"],
            output_modalities=["video"],
            protocol="minimax",
            billing_profile="seedance_tokens",
        ),
    )
    endpoint = next(item for item in body["endpoints"] if item["id"] == "ep-seedance")
    assert endpoint["billing_profile"] == "seedance_tokens"

    # Omitting it on a later save clears it back to unset rather than
    # silently keeping the old value — the payload is a full replace, same
    # as every other field on this endpoint.
    body = _upsert(
        client,
        admin,
        "ep-seedance",
        _media_payload(
            model="doubao-seedance-2-5-260628",
            input_modalities=["text", "image"],
            output_modalities=["video"],
            protocol="minimax",
        ),
    )
    endpoint = next(item for item in body["endpoints"] if item["id"] == "ep-seedance")
    assert endpoint["billing_profile"] is None


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
