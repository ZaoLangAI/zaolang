"""Single-endpoint connectivity checks never enter routing or persist outputs."""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

from app.models.enums import Operation
from app.platform_config.schemas import LlmProviderEndpoint
from app.providers import connectivity


def _general(**overrides: object) -> LlmProviderEndpoint:
    values: dict[str, object] = {
        "name": "General",
        "base_url": "https://gateway.invalid/v1",
        "api_key": "secret",
        "kind": "general",
        "model": "model-a",
    }
    values.update(overrides)
    return LlmProviderEndpoint.model_validate(values)


def _media(**overrides: object) -> LlmProviderEndpoint:
    values: dict[str, object] = {
        "name": "Media",
        "base_url": "https://media.invalid",
        "api_key": "secret",
        "kind": "media",
        "model": "media-a",
        "input_modalities": ["text", "image", "video"],
        "output_modalities": ["video"],
    }
    values.update(overrides)
    return LlmProviderEndpoint.model_validate(values)


def test_general_probe_uses_the_configured_model_and_production_request_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_client = object()
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        connectivity.llm_client, "client_for_endpoint", lambda endpoint: fake_client
    )

    def fake_call(**kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="OK"))])

    monkeypatch.setattr(connectivity.llm_client, "call_gateway_once", fake_call)
    result = connectivity.validate_endpoint(_general(model="first"))

    assert result.usable is True
    assert result.target_model == "first"
    assert captured["client"] is fake_client
    assert captured["model"] == "first"
    assert captured["expect_json"] is False


def test_general_endpoint_requires_a_declared_model() -> None:
    with pytest.raises(ValueError):
        _general(model="")


def test_a_legacy_multi_model_endpoint_collapses_to_its_first_model() -> None:
    """Config written before one-model-per-endpoint must still load."""
    endpoint = LlmProviderEndpoint.model_validate(
        {
            "name": "General",
            "base_url": "https://gateway.invalid/v1",
            "api_key": "secret",
            "kind": "general",
            "models": ["first", "second"],
        }
    )

    assert endpoint.model == "first"


def test_media_video_probe_uses_official_h3_shape_without_undocumented_cancel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    def fake_post(self, path, **kwargs):  # type: ignore[no-untyped-def]
        calls.append((path, kwargs))
        request = httpx.Request("POST", f"https://media.invalid{path}")
        return httpx.Response(200, json={"id": "task-1"}, request=request)

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    result = connectivity.validate_endpoint(_media(model="minimax-h3"))

    assert result.probe_type == Operation.TEXT_TO_VIDEO.value
    assert result.reachable is True and result.usable is True
    assert [path for path, _ in calls] == ["/ai/v1/videos"]
    assert calls[0][1]["json"]["model"] == "minimax-h3"  # type: ignore[index]
    assert calls[0][1]["json"]["duration"] == 5  # type: ignore[index]
    assert calls[0][1]["json"]["resolution"] == "2K"  # type: ignore[index]
    assert calls[0][1]["json"]["aspect_ratio"] == "16:9"  # type: ignore[index]
    assert result.external_task_id == "task-1"


def test_media_text_to_image_probe_uses_generations_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    def fake_post(self, path, **kwargs):  # type: ignore[no-untyped-def]
        calls.append((path, kwargs))
        request = httpx.Request("POST", f"https://media.invalid{path}")
        return httpx.Response(200, json={"data": [{"b64_json": "abc"}]}, request=request)

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    result = connectivity.validate_endpoint(
        _media(input_modalities=["text"], output_modalities=["image"])
    )

    assert result.probe_type == Operation.TEXT_TO_IMAGE.value
    assert result.usable is True
    assert [path for path, _ in calls] == ["/v1/images/generations"]
    assert "image" not in calls[0][1]["json"]  # type: ignore[index]
    assert calls[0][1]["json"]["size"] == "1024x1024"  # type: ignore[index]


def test_media_image_probe_does_not_double_v1_when_base_includes_v1(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, str] = {}

    def fake_post(self, path, **kwargs):  # type: ignore[no-untyped-def]
        captured["base"] = str(self.base_url).rstrip("/")
        captured["path"] = path
        request = httpx.Request("POST", f"https://aihubmix.com{path}")
        return httpx.Response(200, json={"data": [{"b64_json": "abc"}]}, request=request)

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    result = connectivity.validate_endpoint(
        _media(
            base_url="https://aihubmix.com/v1",
            input_modalities=["text"],
            output_modalities=["image"],
        )
    )

    assert result.usable is True
    assert captured["base"] == "https://aihubmix.com"
    assert captured["path"] == "/v1/images/generations"


def test_media_image_to_image_probe_sends_a_data_uri_not_multipart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    def fake_post(self, path, **kwargs):  # type: ignore[no-untyped-def]
        calls.append((path, kwargs))
        request = httpx.Request("POST", f"https://media.invalid{path}")
        return httpx.Response(
            200, json={"data": [{"url": "https://cdn.invalid/out.png"}]}, request=request
        )

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    result = connectivity.validate_endpoint(
        _media(input_modalities=["image"], output_modalities=["image"])
    )

    assert result.probe_type == Operation.IMAGE_TO_IMAGE.value
    assert result.usable is True
    assert [path for path, _ in calls] == ["/v1/images/generations"]
    body = calls[0][1]["json"]  # type: ignore[index]
    assert isinstance(body["image"], str) and body["image"].startswith("data:image/png;base64,")
    assert "files" not in calls[0][1]


def test_media_http_rejection_is_reachable_but_not_usable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_post(self, path, **kwargs):  # type: ignore[no-untyped-def]
        request = httpx.Request("POST", f"https://media.invalid{path}")
        return httpx.Response(401, json={"error": "secret detail"}, request=request)

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    result = connectivity.validate_endpoint(
        _media(
            input_modalities=["text"],
            output_modalities=["audio"],
        )
    )

    assert result.reachable is True
    assert result.usable is False
    assert result.provider_status_code == 401
    assert result.error_code == "auth_failed"


def test_media_timeout_is_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_post(self, path, **kwargs):  # type: ignore[no-untyped-def]
        request = httpx.Request("POST", f"https://media.invalid{path}")
        raise httpx.ReadTimeout("secret upstream detail", request=request)

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    result = connectivity.validate_endpoint(_media())

    assert result.reachable is False
    assert result.usable is False
    assert result.error_code == "timeout"


def test_media_403_is_access_denied_and_provider_detail_is_redacted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_post(self, path, **kwargs):  # type: ignore[no-untyped-def]
        request = httpx.Request("POST", f"https://media.invalid{path}")
        return httpx.Response(
            403,
            json={
                "error": {
                    "code": "model_not_authorized",
                    "message": "Bearer secret cannot use https://private.invalid/task?token=abc",
                }
            },
            request=request,
        )

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    result = connectivity.validate_endpoint(_media(api_key="secret"))

    assert result.error_code == "access_forbidden"
    assert result.provider_error_code == "model_not_authorized"
    assert result.provider_error_message is not None
    assert "secret" not in result.provider_error_message
    assert "private.invalid" not in result.provider_error_message
