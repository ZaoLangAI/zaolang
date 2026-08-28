"""AiHubMix media provider: image/audio sync calls, video task polling."""

from __future__ import annotations

import base64
import io

import httpx
import pytest
from PIL import Image

from app.config import get_settings
from app.models.enums import Operation
from app.providers.aihubmix_media import AiHubMixMediaProvider
from app.providers.base import GenerationRequest, ProviderReference
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


def test_image_to_image_calls_generations_with_a_signed_reference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A real (non-`local`/`test`) deployment's publicly reachable bucket
    stays on the cheap presigned-URL path — see the base64 test below for
    the `local`/`test` path this same helper takes by default."""
    monkeypatch.setattr(get_settings(), "app_env", "production", raising=False)
    reference_key = "test/reference-for-edit.png"
    s3.put_object(reference_key, base64.b64decode(_png_b64((90, 5, 5))), content_type="image/png")
    b64 = _png_b64()
    calls: list[tuple[str, dict[str, object]]] = []

    monkeypatch.setattr(
        s3,
        "presign_get",
        lambda key, **kwargs: f"https://signed.invalid/{key}",
    )

    def fake_post(self, url, **kwargs):  # type: ignore[no-untyped-def]
        calls.append((url, kwargs))
        return _FakeResponse(json_body={"data": [{"b64_json": b64}]})

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    provider = _provider(Operation.IMAGE_TO_IMAGE.value)
    result = provider.submit(
        _request(Operation.IMAGE_TO_IMAGE.value, reference_object_keys=[reference_key])
    )

    assert result.succeeded is True
    assert [url for url, _ in calls] == ["/v1/images/generations"]
    assert calls[0][1]["json"]["image"] == f"https://signed.invalid/{reference_key}"
    assert "files" not in calls[0][1]


def test_image_to_image_embeds_the_reference_as_base64_in_local_and_test_envs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The bug: aihubmix (a real external HTTP API) can never reach
    `http://localhost:9000` (`local`/`test`'s default `s3_public_endpoint_
    url`), so a presigned URL there is silently unfetchable and the
    provider quietly generates from the prompt alone with no actual
    reference — see `Settings.embed_reference_images_as_base64`. This is
    already the default test-suite `app_env` (`tests/conftest.py`), so no
    monkeypatching of settings is needed here, unlike the signed-URL test
    above."""
    assert get_settings().embed_reference_images_as_base64 is True
    reference_key = "test/reference-for-edit-base64.png"
    reference_bytes = base64.b64decode(_png_b64((90, 5, 5)))
    s3.put_object(reference_key, reference_bytes, content_type="image/png")
    b64 = _png_b64()
    calls: list[tuple[str, dict[str, object]]] = []

    def fake_post(self, url, **kwargs):  # type: ignore[no-untyped-def]
        calls.append((url, kwargs))
        return _FakeResponse(json_body={"data": [{"b64_json": b64}]})

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    provider = _provider(Operation.IMAGE_TO_IMAGE.value)
    result = provider.submit(
        _request(Operation.IMAGE_TO_IMAGE.value, reference_object_keys=[reference_key])
    )

    assert result.succeeded is True
    image_field = calls[0][1]["json"]["image"]
    assert isinstance(image_field, str)
    assert image_field.startswith("data:image/png;base64,")
    encoded = image_field.removeprefix("data:image/png;base64,")
    assert base64.b64decode(encoded) == reference_bytes


def test_image_to_image_routes_a_qwen_model_through_the_edit_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`/v1/images/generations` + an ad-hoc `image` field is not a
    documented AiHubMix contract for Qwen (a 2026-08-19 live check showed it
    carries the reference through only weakly, if at all). A Qwen model
    must go through the real editing endpoint instead — see
    `AiHubMixMediaProvider._submit_qwen_image_edit`."""
    reference_key = "test/reference-for-qwen-edit.png"
    reference_bytes = base64.b64decode(_png_b64((90, 5, 5)))
    s3.put_object(reference_key, reference_bytes, content_type="image/png")
    output_png = base64.b64decode(_png_b64())
    calls: list[tuple[str, dict[str, object]]] = []

    def fake_post(self, url, **kwargs):  # type: ignore[no-untyped-def]
        calls.append((url, kwargs))
        return _FakeResponse(json_body={"output": [{"url": "https://cdn.invalid/edited.png"}]})

    def fake_get(self, url, **kwargs):  # type: ignore[no-untyped-def]
        assert url == "https://cdn.invalid/edited.png"
        return _FakeResponse(content=output_png)

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    monkeypatch.setattr(httpx.Client, "get", fake_get)
    provider = _provider(Operation.IMAGE_TO_IMAGE.value, model="qwen-image-3.0")
    result = provider.submit(
        _request(
            Operation.IMAGE_TO_IMAGE.value,
            reference_object_keys=[reference_key],
            aspect_ratio="3:4",
            seed=7,
        )
    )

    assert result.succeeded is True
    assert s3.get_object(result.object_key) == output_png
    assert [url for url, _ in calls] == ["/v1/models/qianfan/qwen-image-edit/predictions"]
    body = calls[0][1]["json"]
    assert "model" not in body
    assert body["input"]["prompt"] == "一只在雨夜霓虹街道上奔跑的机械狐狸"
    assert "size" not in body["input"]
    assert body["input"]["seed"] == 7
    image_field = body["input"]["image"]
    assert isinstance(image_field, str)
    assert image_field.startswith("data:image/png;base64,")
    encoded = image_field.removeprefix("data:image/png;base64,")
    assert base64.b64decode(encoded) == reference_bytes


def test_qwen_image_edit_caps_references_at_three(monkeypatch: pytest.MonkeyPatch) -> None:
    keys = [f"test/qwen-multi-ref-{i}.png" for i in range(5)]
    for i, key in enumerate(keys):
        s3.put_object(key, base64.b64decode(_png_b64((i, i, i))), content_type="image/png")
    output_png = base64.b64decode(_png_b64())
    calls: list[dict[str, object]] = []

    def fake_post(self, url, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(kwargs["json"])
        return _FakeResponse(json_body={"output": [{"url": "https://cdn.invalid/edited.png"}]})

    def fake_get(self, url, **kwargs):  # type: ignore[no-untyped-def]
        return _FakeResponse(content=output_png)

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    monkeypatch.setattr(httpx.Client, "get", fake_get)
    provider = _provider(Operation.IMAGE_TO_IMAGE.value, model="qwen-image-edit")
    result = provider.submit(
        _request(Operation.IMAGE_TO_IMAGE.value, reference_object_keys=keys)
    )

    assert result.succeeded is True
    assert len(calls[0]["input"]["image"]) == 3


def test_qwen_image_edit_missing_output_url_is_a_provider_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reference_key = "test/reference-for-qwen-edit-missing.png"
    s3.put_object(
        reference_key, base64.b64decode(_png_b64((4, 4, 4))), content_type="image/png"
    )

    def fake_post(self, url, **kwargs):  # type: ignore[no-untyped-def]
        return _FakeResponse(json_body={"output": []})

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    provider = _provider(Operation.IMAGE_TO_IMAGE.value, model="qwen-image-3.0")
    result = provider.submit(
        _request(Operation.IMAGE_TO_IMAGE.value, reference_object_keys=[reference_key])
    )

    assert result.succeeded is False
    assert result.failure_code == "PROVIDER_INVALID_RESPONSE"


def test_a_reference_over_the_base64_limit_falls_back_to_a_signed_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.providers import aihubmix_media

    monkeypatch.setattr(aihubmix_media, "_MAX_BASE64_REFERENCE_BYTES", 8)
    reference_key = "test/reference-too-big-for-base64.png"
    s3.put_object(
        reference_key, base64.b64decode(_png_b64((1, 2, 3))), content_type="image/png"
    )
    monkeypatch.setattr(
        s3,
        "presign_get",
        lambda key, **kwargs: f"https://signed.invalid/{key}",
    )
    b64 = _png_b64()
    calls: list[tuple[str, dict[str, object]]] = []

    def fake_post(self, url, **kwargs):  # type: ignore[no-untyped-def]
        calls.append((url, kwargs))
        return _FakeResponse(json_body={"data": [{"b64_json": b64}]})

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    provider = _provider(Operation.IMAGE_TO_IMAGE.value)
    result = provider.submit(
        _request(Operation.IMAGE_TO_IMAGE.value, reference_object_keys=[reference_key])
    )

    assert result.succeeded is True
    assert calls[0][1]["json"]["image"] == f"https://signed.invalid/{reference_key}"


def test_text_to_image_downloads_a_url_response(monkeypatch: pytest.MonkeyPatch) -> None:
    png = base64.b64decode(_png_b64())

    def fake_post(self, url, **kwargs):  # type: ignore[no-untyped-def]
        return _FakeResponse(json_body={"data": [{"url": "https://cdn.invalid/out.png"}]})

    def fake_get(self, url, **kwargs):  # type: ignore[no-untyped-def]
        assert url == "https://cdn.invalid/out.png"
        return _FakeResponse(content=png)

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    monkeypatch.setattr(httpx.Client, "get", fake_get)
    provider = _provider(Operation.TEXT_TO_IMAGE.value)
    result = provider.submit(_request(Operation.TEXT_TO_IMAGE.value))

    assert result.succeeded is True
    assert result.object_key is not None
    assert s3.get_object(result.object_key) == png


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


def test_video_analysis_submits_video_url_and_parses_structured_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        s3, "presign_get", lambda key, **kwargs: f"https://signed.invalid/{key}"
    )
    captured: dict = {}

    def fake_post(self, url, **kwargs):  # type: ignore[no-untyped-def]
        assert url == "/v1/chat/completions"
        captured.update(kwargs["json"])
        body = {
            "summary": "一段城市夜景运镜展示",
            "composed_prompt": "霓虹夜色下的城市航拍，缓慢推进",
            "style_tags": ["cyberpunk", "夜景"],
            "pacing": "舒缓长镜头",
            "shots": [
                {
                    "time_range": "00:00-00:03",
                    "camera_movement": "推镜",
                    "scene": "城市天际线",
                    "subject_action": "无人机缓慢前进",
                    "lighting_mood": "霓虹冷色调",
                    "transition_in": "淡入",
                }
            ],
        }
        return _FakeResponse(
            json_body={"choices": [{"message": {"content": f"```json\n{__import__('json').dumps(body)}\n```"}}]}
        )

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    provider = _provider(Operation.VIDEO_ANALYSIS.value, model="qwen-vl-max")
    result = provider.submit(
        _request(
            Operation.VIDEO_ANALYSIS.value,
            prompt="重点关注镜头切换节奏",
            references=[ProviderReference(object_key="source.mp4", media_type="video")],
        )
    )

    assert result.succeeded is True
    assert result.object_key is None
    assert result.output_json is not None
    assert result.output_json["summary"] == "一段城市夜景运镜展示"
    assert result.output_json["shots"][0]["camera_movement"] == "推镜"
    content = captured["messages"][0]["content"]
    assert content[0]["video_url"]["url"] == "https://signed.invalid/source.mp4"
    assert "重点关注镜头切换节奏" in content[1]["text"]


def test_video_analysis_fails_without_a_video_reference(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_post(self, url, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("must not call the gateway without a reference")

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    provider = _provider(Operation.VIDEO_ANALYSIS.value, model="qwen-vl-max")
    result = provider.submit(_request(Operation.VIDEO_ANALYSIS.value, references=[]))

    assert result.succeeded is False
    assert result.failure_code == "PROVIDER_INVALID_RESPONSE"


def test_video_submit_returns_pending_without_waiting_for_the_render(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Submitting must not block: a render takes minutes, and holding the
    worker for that long is exactly what the async task table exists to
    avoid."""
    gets: list[str] = []

    def fake_post(self, url, **kwargs):  # type: ignore[no-untyped-def]
        assert url == "/ai/v1/videos"
        assert kwargs["json"]["resolution"] == "2K"
        return _FakeResponse(json_body={"id": "task-123"})

    def fake_get(self, url, **kwargs):  # type: ignore[no-untyped-def]
        gets.append(url)
        raise AssertionError("submit must not poll")

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    monkeypatch.setattr(httpx.Client, "get", fake_get)
    provider = _provider(Operation.TEXT_TO_VIDEO.value, model="minimax-h3")
    result = provider.submit(_request(Operation.TEXT_TO_VIDEO.value, duration_seconds=6))

    assert result.pending is True
    assert result.succeeded is False
    assert result.external_task_id == "task-123"
    assert gets == []


def test_h3_video_payload_types_input_references_and_frame_images(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payloads: list[dict] = []

    monkeypatch.setattr(
        s3,
        "presign_get",
        lambda key, **kwargs: f"https://signed.invalid/{key}",
    )

    def fake_post(self, url, **kwargs):  # type: ignore[no-untyped-def]
        payloads.append(kwargs["json"])
        return _FakeResponse(json_body={"id": f"task-{len(payloads)}"})

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    provider = _provider(Operation.IMAGE_TO_VIDEO.value, model="minimax-h3")
    provider.submit(
        _request(
            Operation.IMAGE_TO_VIDEO.value,
            duration_seconds=5,
            references=[
                ProviderReference(object_key="image.png", media_type="image"),
                ProviderReference(object_key="motion.mp4", media_type="video"),
            ],
        )
    )
    provider.submit(
        _request(
            Operation.IMAGE_TO_VIDEO.value,
            duration_seconds=5,
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

    assert [item["type"] for item in payloads[0]["input_references"]] == [
        "image_url",
        "video_url",
    ]
    assert all("role" not in item for item in payloads[0]["input_references"])
    assert "frame_images" not in payloads[0]
    assert [item["frame_type"] for item in payloads[1]["frame_images"]] == [
        "first_frame",
        "last_frame",
    ]
    assert "input_references" not in payloads[1]


def test_h3_cancel_does_not_call_an_undocumented_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_post(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("must not call cancel")

    monkeypatch.setattr(httpx.Client, "post", fail_post)
    assert _provider(Operation.TEXT_TO_VIDEO.value, model="minimax-h3").cancel("task-1") is False


def test_polling_a_finished_video_downloads_and_stores_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    video_bytes = b"fake-mp4-bytes"

    def fake_get(self, url, **kwargs):  # type: ignore[no-untyped-def]
        if url.endswith("/content"):
            return _FakeResponse(content=video_bytes)
        return _FakeResponse(json_body={"status": "completed", "output": [{}]})

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    provider = _provider(Operation.TEXT_TO_VIDEO.value)
    request = _request(Operation.TEXT_TO_VIDEO.value, duration_seconds=6)
    result = provider.poll("task-123", request)

    assert result.succeeded is True
    assert result.mime_type == "video/mp4"
    assert result.duration_ms == 6_000
    assert result.external_task_id == "task-123"
    assert s3.get_object(result.object_key) == video_bytes


def test_polling_a_multi_output_task_asks_for_a_specific_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The plain content path answers `400 result_id_required` when a task
    produced more than one output."""
    requested: list[str] = []

    def fake_get(self, url, **kwargs):  # type: ignore[no-untyped-def]
        requested.append(url)
        if "/content" in url:
            return _FakeResponse(content=b"mp4")
        return _FakeResponse(
            json_body={
                "status": "completed",
                "output": [{"result_id": "res-1"}, {"result_id": "res-2"}],
            }
        )

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    provider = _provider(Operation.TEXT_TO_VIDEO.value)
    provider.poll("task-multi", _request(Operation.TEXT_TO_VIDEO.value))

    assert requested[-1] == "/ai/v1/tasks/task-multi/content/res-1"


def test_polling_an_unfinished_video_stays_pending(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get(self, url, **kwargs):  # type: ignore[no-untyped-def]
        return _FakeResponse(json_body={"status": "running"})

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    provider = _provider(Operation.IMAGE_TO_VIDEO.value)
    result = provider.poll("task-stuck", _request(Operation.IMAGE_TO_VIDEO.value))

    assert result.pending is True
    assert result.failure_code is None


def test_a_failed_video_task_is_reported_as_a_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get(self, url, **kwargs):  # type: ignore[no-untyped-def]
        return _FakeResponse(json_body={"status": "failed", "error": "上游拒绝"})

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    provider = _provider(Operation.TEXT_TO_VIDEO.value)
    result = provider.poll("task-failed", _request(Operation.TEXT_TO_VIDEO.value))

    assert result.pending is False
    assert result.succeeded is False
    assert result.failure_code == "PROVIDER_TASK_FAILED"


def test_failed_task_with_output_is_downloaded_for_quality_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_get(self, url, **kwargs):  # type: ignore[no-untyped-def]
        if "/content" in url:
            return _FakeResponse(content=b"partial-mp4")
        return _FakeResponse(
            json_body={
                "status": "failed",
                "error": "render_incomplete",
                "output": [{"result_id": "partial-1"}],
            }
        )

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    provider = _provider(Operation.TEXT_TO_VIDEO.value)
    result = provider.poll("task-partial", _request(Operation.TEXT_TO_VIDEO.value))

    assert result.succeeded is True
    assert result.metadata["partial_output"] is True
    assert result.metadata["upstream_status"] == "failed"
    assert s3.get_object(result.object_key) == b"partial-mp4"


def test_a_transport_error_while_polling_keeps_the_task_pending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A blip in the network is not the render failing — the deadline, owned
    by the caller, is what eventually gives up."""

    def fake_get(self, url, **kwargs):  # type: ignore[no-untyped-def]
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    provider = _provider(Operation.TEXT_TO_VIDEO.value)
    result = provider.poll("task-flaky", _request(Operation.TEXT_TO_VIDEO.value))

    assert result.pending is True
    assert result.failure_code is None


def test_a_transport_error_degrades_to_a_temporary_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_post(self, url, **kwargs):  # type: ignore[no-untyped-def]
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    provider = _provider(Operation.TEXT_TO_IMAGE.value)
    result = provider.submit(_request(Operation.TEXT_TO_IMAGE.value))

    assert result.succeeded is False
    assert result.failure_code == "PROVIDER_TEMPORARY_FAILURE"


def test_a_read_timeout_reports_how_long_we_waited(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_post(self, url, **kwargs):  # type: ignore[no-untyped-def]
        request = httpx.Request("POST", "https://aihubmix.invalid/v1/images/generations")
        raise httpx.ReadTimeout("timed out", request=request)

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    result = _provider(Operation.TEXT_TO_IMAGE.value).submit(
        _request(Operation.TEXT_TO_IMAGE.value)
    )

    assert result.succeeded is False
    assert result.failure_code == "PROVIDER_TEMPORARY_FAILURE"
    assert result.metadata["detail"] == "ReadTimeout after 5s"


def test_join_media_url_does_not_double_v1() -> None:
    from app.providers.aihubmix_media import join_media_url, media_client_base, media_request_path

    assert (
        join_media_url("https://aihubmix.com/v1", "/v1/images/generations")
        == "https://aihubmix.com/v1/images/generations"
    )
    assert media_client_base("https://aihubmix.com/v1") == "https://aihubmix.com"
    assert media_request_path("https://aihubmix.com/v1", "/v1/images/generations") == (
        "/v1/images/generations"
    )
    assert (
        join_media_url("https://aihubmix.com", "/ai/v1/videos") == "https://aihubmix.com/ai/v1/videos"
    )
    assert media_request_path("https://proxy.example/openai/v1", "/v1/images/generations") == (
        "/openai/v1/images/generations"
    )


def test_image_submit_strips_v1_from_client_base(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, str] = {}
    b64 = _png_b64()

    def fake_post(self, url, **kwargs):  # type: ignore[no-untyped-def]
        captured["base"] = str(self.base_url).rstrip("/")
        captured["url"] = url
        captured["size"] = kwargs["json"]["size"]
        return _FakeResponse(json_body={"data": [{"b64_json": b64}]})

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    provider = AiHubMixMediaProvider(
        endpoint_id="ep-test",
        capability_tag=Operation.TEXT_TO_IMAGE.value,
        model="qwen-image-3.0",
        base_url="https://aihubmix.com/v1",
        api_key="test-key",
        timeout_ms=5_000,
    )
    result = provider.submit(_request(Operation.TEXT_TO_IMAGE.value, quality_tier="preview"))

    assert result.succeeded is True
    assert captured["base"] == "https://aihubmix.com"
    assert captured["url"] == "/v1/images/generations"
    assert captured["size"] == "1024x576"


def test_http_status_error_includes_status_and_redacted_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_post(self, url, **kwargs):  # type: ignore[no-untyped-def]
        request = httpx.Request("POST", "https://aihubmix.invalid/v1/images/generations")
        return httpx.Response(
            404,
            text='{"error":{"code":"endpoint_not_found","message":"Bearer test-key missing"}}',
            request=request,
        )

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    result = _provider(Operation.TEXT_TO_IMAGE.value).submit(
        _request(Operation.TEXT_TO_IMAGE.value)
    )

    assert result.succeeded is False
    assert result.failure_code == "PROVIDER_INVALID_RESPONSE"
    detail = result.metadata["detail"]
    assert "HTTP 404" in detail
    assert "endpoint_not_found" in detail
    assert "test-key" not in detail
    assert "[redacted]" in detail
