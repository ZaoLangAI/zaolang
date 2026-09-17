"""Official MiniMax Video V2 / Metaso media provider."""

from __future__ import annotations

import httpx
import pytest

from app.models.enums import Operation
from app.providers.base import GenerationRequest, ProviderReference
from app.providers.minimax_v2_media import (
    MINIMAX_H3_MODEL,
    MinimaxV2MediaProvider,
    build_generation_body,
    extract_task_id,
    probe_video_body,
    video_model_profile,
)
from app.storage import s3


def _provider() -> MinimaxV2MediaProvider:
    return MinimaxV2MediaProvider(
        endpoint_id="ep-metaso",
        capability_tag=Operation.TEXT_TO_VIDEO.value,
        model=MINIMAX_H3_MODEL,
        base_url="https://metaso.cn/api/minimax",
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
        "duration_seconds": 5,
    }
    defaults.update(overrides)
    return GenerationRequest(**defaults)  # type: ignore[arg-type]


class _FakeResponse:
    def __init__(
        self,
        *,
        json_body: dict | None = None,
        content: bytes = b"",
        status_code: int = 200,
    ) -> None:
        self._json_body = json_body
        self.content = content
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            request = httpx.Request("GET", "https://metaso.cn/api/minimax/v2/video_generation")
            raise httpx.HTTPStatusError(
                "error",
                request=request,
                response=httpx.Response(self.status_code, request=request),
            )

    def json(self) -> dict:
        assert self._json_body is not None
        return self._json_body


def test_h3_profile_uses_official_six_ratios_plus_adaptive() -> None:
    profile = video_model_profile(MINIMAX_H3_MODEL)
    assert profile is not None
    assert profile.min_duration_seconds == 4
    assert profile.max_duration_seconds == 15
    assert profile.resolutions == frozenset({"768P", "2K"})
    assert "3:2" not in profile.aspect_ratios
    assert "adaptive" in profile.aspect_ratios
    assert profile.reference_modes == frozenset({"input_references", "frame_images"})


def test_text_to_video_body_uses_content_not_input() -> None:
    body = build_generation_body(_request(Operation.TEXT_TO_VIDEO.value))
    assert body["model"] == MINIMAX_H3_MODEL
    assert body["content"] == [{"type": "text", "text": "一只在雨夜霓虹街道上奔跑的机械狐狸"}]
    assert body["duration"] == 5
    assert body["ratio"] == "16:9"
    assert body["resolution"] == "2K"
    assert "input" not in body
    assert "frame_images" not in body
    assert "input_references" not in body


def test_text_to_video_remaps_adaptive_ratio_to_16_9() -> None:
    body = build_generation_body(
        _request(Operation.TEXT_TO_VIDEO.value, aspect_ratio="adaptive")
    )
    assert body["ratio"] == "16:9"


def test_rejects_an_out_of_range_duration() -> None:
    with pytest.raises(ValueError, match="duration must be between 4 and 15"):
        build_generation_body(_request(Operation.TEXT_TO_VIDEO.value, duration_seconds=20))


def test_rejects_an_empty_prompt() -> None:
    with pytest.raises(ValueError, match="non-empty text prompt"):
        build_generation_body(_request(Operation.TEXT_TO_VIDEO.value, prompt="   "))


def test_first_last_frame_forces_adaptive_ratio(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(s3, "presign_get", lambda key, **kwargs: f"https://signed.invalid/{key}")
    body = build_generation_body(
        _request(
            Operation.IMAGE_TO_VIDEO.value,
            aspect_ratio="16:9",
            references=[
                ProviderReference(
                    object_key="first.png", media_type="image", frame_type="first_frame"
                ),
                ProviderReference(
                    object_key="last.png", media_type="image", frame_type="last_frame"
                ),
            ],
        )
    )
    assert body["ratio"] == "adaptive"
    assert body["content"][1]["role"] == "first_frame"
    assert body["content"][2]["role"] == "last_frame"


def test_generic_video_reference_gets_a_reference_role(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(s3, "presign_get", lambda key, **kwargs: f"https://signed.invalid/{key}")
    body = build_generation_body(
        _request(
            Operation.VIDEO_TO_VIDEO.value,
            aspect_ratio="adaptive",
            references=[ProviderReference(object_key="ref.mp4", media_type="video")],
        )
    )
    assert body["ratio"] == "adaptive"
    assert body["content"][1] == {
        "type": "video_url",
        "video_url": {"url": "https://signed.invalid/ref.mp4"},
        "role": "reference_video",
    }


def test_frame_and_reference_roles_are_mutually_exclusive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(s3, "presign_get", lambda key, **kwargs: f"https://signed.invalid/{key}")
    with pytest.raises(ValueError, match="mutually exclusive"):
        build_generation_body(
            _request(
                Operation.VIDEO_TO_VIDEO.value,
                references=[
                    ProviderReference(
                        object_key="first.png", media_type="image", frame_type="first_frame"
                    ),
                    ProviderReference(object_key="ref.mp4", media_type="video"),
                ],
            )
        )


def test_extract_task_id_tolerates_nested_and_flat_shapes() -> None:
    assert extract_task_id({"task_id": "424010985738629"}) == "424010985738629"
    assert extract_task_id({"task": {"id": "nested-1"}}) == "nested-1"
    assert extract_task_id({"id": "flat-1"}) == "flat-1"
    assert extract_task_id({}) is None


def test_probe_body_is_a_cheap_768p_text_to_video() -> None:
    body = probe_video_body(MINIMAX_H3_MODEL)
    assert body["resolution"] == "768P"
    assert body["duration"] == 4
    assert body["ratio"] == "16:9"


def test_submit_returns_pending_with_task_id(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_post(self, url, **kwargs):  # type: ignore[no-untyped-def]
        captured["url"] = url
        captured["json"] = kwargs["json"]
        return _FakeResponse(json_body={"task_id": "424010985738629"})

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    result = _provider().submit(_request(Operation.TEXT_TO_VIDEO.value))

    assert captured["url"] == "/api/minimax/v2/video_generation"
    assert captured["json"]["content"][0]["type"] == "text"
    assert result.pending is True
    assert result.external_task_id == "424010985738629"


def test_submit_accepts_nested_task_id(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_post(self, url, **kwargs):  # type: ignore[no-untyped-def]
        return _FakeResponse(json_body={"task": {"id": "nested-task"}})

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    result = _provider().submit(_request(Operation.TEXT_TO_VIDEO.value))
    assert result.external_task_id == "nested-task"


def test_submit_missing_task_id_is_a_provider_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_post(self, url, **kwargs):  # type: ignore[no-untyped-def]
        return _FakeResponse(json_body={"usage": {}})

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    result = _provider().submit(_request(Operation.TEXT_TO_VIDEO.value))
    assert result.succeeded is False
    assert result.failure_code == "PROVIDER_INVALID_RESPONSE"


def test_poll_downloads_the_finished_video(monkeypatch: pytest.MonkeyPatch) -> None:
    video_bytes = b"h3-mp4-bytes"
    video_url = "https://cdn.example.com/h3-generated-2k-output.mp4"

    def fake_get(self, url, **kwargs):  # type: ignore[no-untyped-def]
        if url == video_url:
            return _FakeResponse(content=video_bytes)
        assert url == "/api/minimax/v2/query/video_generation/424010985738629"
        return _FakeResponse(
            json_body={
                "task": {
                    "id": "424010985738629",
                    "status": "succeeded",
                    "content": {"url": video_url},
                }
            }
        )

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    result = _provider().poll(
        "424010985738629", _request(Operation.TEXT_TO_VIDEO.value, duration_seconds=5)
    )

    assert result.succeeded is True
    assert result.mime_type == "video/mp4"
    assert s3.get_object(result.object_key) == video_bytes


def test_poll_stays_pending_while_running(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get(self, url, **kwargs):  # type: ignore[no-untyped-def]
        return _FakeResponse(json_body={"task": {"status": "running"}})

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    result = _provider().poll("task-1", _request(Operation.TEXT_TO_VIDEO.value))
    assert result.pending is True
    assert result.succeeded is False


def test_poll_http_error_stays_pending(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get(self, url, **kwargs):  # type: ignore[no-untyped-def]
        raise httpx.ConnectError("transient")

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    result = _provider().poll("task-1", _request(Operation.TEXT_TO_VIDEO.value))
    assert result.pending is True
    assert result.succeeded is False
    assert result.failure_code is None


def test_poll_failed_status_is_a_task_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get(self, url, **kwargs):  # type: ignore[no-untyped-def]
        return _FakeResponse(
            json_body={
                "task": {
                    "status": "failed",
                    "error": {"code": "1026", "message": "sensitive content"},
                }
            }
        )

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    result = _provider().poll("task-1", _request(Operation.TEXT_TO_VIDEO.value))
    assert result.succeeded is False
    assert result.failure_code == "PROVIDER_TASK_FAILED"
    assert "sensitive" in str(result.metadata.get("detail"))


def test_cancel_deletes_the_official_v2_path(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[str] = []

    def fake_delete(self, url, **kwargs):  # type: ignore[no-untyped-def]
        captured.append(url)
        return _FakeResponse(json_body={"action": "cancelled", "status": "cancelled"})

    monkeypatch.setattr(httpx.Client, "delete", fake_delete)
    assert _provider().cancel("424010985738629") is True
    assert captured == ["/api/minimax/v2/video_generation/424010985738629"]


def test_cancel_returns_false_on_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_delete(self, url, **kwargs):  # type: ignore[no-untyped-def]
        raise httpx.ConnectError("boom")

    monkeypatch.setattr(httpx.Client, "delete", fake_delete)
    assert _provider().cancel("task-1") is False
