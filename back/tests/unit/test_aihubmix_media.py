"""AiHubMix media provider: image/audio sync calls, video task polling."""

from __future__ import annotations

import base64
import io

import httpx
import pytest
from PIL import Image

from app.models.enums import Operation
from app.providers import aihubmix_media as media_module
from app.providers.aihubmix_media import AiHubMixMediaProvider
from app.providers.base import GenerationRequest
from app.storage import s3


def _png_b64(colour: tuple[int, int, int] = (10, 20, 30), size: tuple[int, int] = (32, 32)) -> str:
    buffer = io.BytesIO()
    Image.new("RGB", size, colour).save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode()


def _provider(capability_tag: str, model: str = "test-model") -> AiHubMixMediaProvider:
    return AiHubMixMediaProvider(
        endpoint_id="ep-test",
        capability_tag=capability_tag,
        model=model,
        base_url="https://aihubmix.invalid",
        api_key="test-key",
        timeout_ms=5_000,
    )


def _request(operation: str, **overrides: object) -> GenerationRequest:
    defaults: dict[str, object] = {
        "job_id": f"job-{operation}",
        "operation": operation,
        "quality_tier": "standard",
        "prompt": "一只在雨夜霓虹街道上奔跑的机械狐狸",
        "aspect_ratio": "16:9",
        "duration_seconds": 4,
    }
    defaults.update(overrides)
    return GenerationRequest(**defaults)  # type: ignore[arg-type]


class _FakeResponse:
    def __init__(self, *, json_body: dict | None = None, content: bytes = b"") -> None:
        self._json_body = json_body
        self.content = content
        self.status_code = 200

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        assert self._json_body is not None
        return self._json_body


def test_text_to_image_generates_and_stores_output(monkeypatch: pytest.MonkeyPatch) -> None:
    b64 = _png_b64()

    def fake_post(self, url, **kwargs):  # type: ignore[no-untyped-def]
        assert url == "/v1/images/generations"
        return _FakeResponse(json_body={"data": [{"b64_json": b64}]})

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    provider = _provider(Operation.TEXT_TO_IMAGE.value)
    result = provider.submit(_request(Operation.TEXT_TO_IMAGE.value))

    assert result.succeeded is True
    assert result.mime_type == "image/png"
    assert result.width == 32 and result.height == 32
    assert result.object_key is not None
    assert s3.get_object(result.object_key) == base64.b64decode(b64)


def test_image_to_image_calls_the_edits_endpoint_with_the_reference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reference_key = "test/reference-for-edit.png"
    s3.put_object(reference_key, base64.b64decode(_png_b64((90, 5, 5))), content_type="image/png")
    b64 = _png_b64()
    calls: list[str] = []

    def fake_post(self, url, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(url)
        assert "files" in kwargs
        return _FakeResponse(json_body={"data": [{"b64_json": b64}]})

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    provider = _provider(Operation.IMAGE_TO_IMAGE.value)
    result = provider.submit(
        _request(Operation.IMAGE_TO_IMAGE.value, reference_object_keys=[reference_key])
    )

    assert result.succeeded is True
    assert calls == ["/v1/images/edits"]


def test_audio_generation_stores_the_raw_response_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    audio_bytes = b"\xff\xfbfake-mp3-payload"

    def fake_post(self, url, **kwargs):  # type: ignore[no-untyped-def]
        assert url == "/v1/audio/speech"
        assert kwargs["json"]["voice"] == "nova"
        return _FakeResponse(content=audio_bytes)

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    provider = _provider(Operation.AUDIO_GENERATION.value)
    result = provider.submit(_request(Operation.AUDIO_GENERATION.value, extra={"voice": "nova"}))

    assert result.succeeded is True
    assert result.mime_type == "audio/mpeg"
    assert result.object_key is not None
    assert s3.get_object(result.object_key) == audio_bytes


def test_video_generation_polls_the_task_until_completion(monkeypatch: pytest.MonkeyPatch) -> None:
    video_bytes = b"fake-mp4-bytes"

    def fake_post(self, url, **kwargs):  # type: ignore[no-untyped-def]
        assert url == "/ai/v1/videos"
        return _FakeResponse(json_body={"task_id": "task-123"})

    def fake_get(self, url, **kwargs):  # type: ignore[no-untyped-def]
        if url.endswith("/content"):
            return _FakeResponse(content=video_bytes)
        return _FakeResponse(json_body={"status": "completed"})

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    monkeypatch.setattr(httpx.Client, "get", fake_get)
    provider = _provider(Operation.TEXT_TO_VIDEO.value)
    result = provider.submit(_request(Operation.TEXT_TO_VIDEO.value, duration_seconds=6))

    assert result.succeeded is True
    assert result.mime_type == "video/mp4"
    assert result.duration_ms == 6_000
    assert result.external_task_id == "task-123"
    assert s3.get_object(result.object_key) == video_bytes


def test_a_failed_video_task_is_reported_without_retrying_forever(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_post(self, url, **kwargs):  # type: ignore[no-untyped-def]
        return _FakeResponse(json_body={"task_id": "task-failed"})

    def fake_get(self, url, **kwargs):  # type: ignore[no-untyped-def]
        return _FakeResponse(json_body={"status": "failed", "error": "上游拒绝"})

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    monkeypatch.setattr(httpx.Client, "get", fake_get)
    provider = _provider(Operation.TEXT_TO_VIDEO.value)
    result = provider.submit(_request(Operation.TEXT_TO_VIDEO.value))

    assert result.succeeded is False
    assert result.failure_code == "PROVIDER_TASK_FAILED"


def test_a_stalled_video_task_times_out_instead_of_blocking_forever(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(media_module, "_VIDEO_POLL_TIMEOUT_SECONDS", 0)
    monkeypatch.setattr(media_module, "_VIDEO_POLL_INTERVAL_SECONDS", 0)
    monkeypatch.setattr(media_module.time, "sleep", lambda _seconds: None)

    def fake_post(self, url, **kwargs):  # type: ignore[no-untyped-def]
        return _FakeResponse(json_body={"task_id": "task-stuck"})

    def fake_get(self, url, **kwargs):  # type: ignore[no-untyped-def]
        return _FakeResponse(json_body={"status": "running"})

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    monkeypatch.setattr(httpx.Client, "get", fake_get)
    provider = _provider(Operation.IMAGE_TO_VIDEO.value)
    result = provider.submit(_request(Operation.IMAGE_TO_VIDEO.value))

    assert result.succeeded is False
    assert result.failure_code == "PROVIDER_TIMEOUT"


def test_a_transport_error_degrades_to_a_temporary_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_post(self, url, **kwargs):  # type: ignore[no-untyped-def]
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    provider = _provider(Operation.TEXT_TO_IMAGE.value)
    result = provider.submit(_request(Operation.TEXT_TO_IMAGE.value))

    assert result.succeeded is False
    assert result.failure_code == "PROVIDER_TEMPORARY_FAILURE"
