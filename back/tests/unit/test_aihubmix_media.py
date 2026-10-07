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


def _provider(
    capability_tag: str, model: str = "test-model", *, protocol: str = "minimax"
) -> AiHubMixMediaProvider:
    return AiHubMixMediaProvider(
        endpoint_id="ep-test",
        capability_tag=capability_tag,
        model=model,
        base_url="https://aihubmix.invalid",
        api_key="test-key",
        timeout_ms=5_000,
        protocol=protocol,
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


def test_gpt_image_2_text_to_image_sends_quality_and_documented_size(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    b64 = _png_b64()
    captured: dict[str, object] = {}

    def fake_post(self, url, **kwargs):  # type: ignore[no-untyped-def]
        captured["url"] = url
        captured["body"] = kwargs["json"]
        return _FakeResponse(json_body={"data": [{"b64_json": b64}]})

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    provider = _provider(Operation.TEXT_TO_IMAGE.value, model="gpt-image-2", protocol="openai")
    result = provider.submit(
        _request(
            Operation.TEXT_TO_IMAGE.value,
            quality_tier="cinematic",
            aspect_ratio="9:16",
        )
    )

    assert result.succeeded is True
    assert captured["url"] == "/v1/images/generations"
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["model"] == "gpt-image-2"
    assert body["quality"] == "high"
    assert body["size"] == "1024x1536"
    assert body["output_format"] == "png"
    assert "image" not in body


def test_gpt_image_2_image_to_image_uses_multipart_edits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reference_key = "test/reference-for-gpt-image-2.png"
    reference_bytes = base64.b64decode(_png_b64((12, 34, 56)))
    s3.put_object(reference_key, reference_bytes, content_type="image/png")
    b64 = _png_b64()
    calls: list[tuple[str, dict[str, object]]] = []

    def fake_post(self, url, **kwargs):  # type: ignore[no-untyped-def]
        calls.append((url, kwargs))
        return _FakeResponse(json_body={"data": [{"b64_json": b64}]})

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    provider = _provider(Operation.IMAGE_TO_IMAGE.value, model="gpt-image-2", protocol="openai")
    result = provider.submit(
        _request(
            Operation.IMAGE_TO_IMAGE.value,
            reference_object_keys=[reference_key],
            quality_tier="preview",
            aspect_ratio="16:9",
        )
    )

    assert result.succeeded is True
    assert result.metadata["endpoint"] == "gpt-image-2-edits"
    assert [url for url, _ in calls] == ["/v1/images/edits"]
    kwargs = calls[0][1]
    assert "json" not in kwargs
    assert kwargs["data"]["model"] == "gpt-image-2"
    assert kwargs["data"]["quality"] == "low"
    assert kwargs["data"]["size"] == "1536x1024"
    assert kwargs["data"]["output_format"] == "png"
    filename, content, mime = kwargs["files"]["image"]
    assert filename == "reference-for-gpt-image-2.png"
    assert content == reference_bytes
    assert mime == "image/png"


def test_non_gpt_image_2_image_to_image_still_uses_generations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reference_key = "test/reference-for-generic-edit.png"
    s3.put_object(reference_key, base64.b64decode(_png_b64((1, 2, 3))), content_type="image/png")
    b64 = _png_b64()
    calls: list[tuple[str, dict[str, object]]] = []

    def fake_post(self, url, **kwargs):  # type: ignore[no-untyped-def]
        calls.append((url, kwargs))
        return _FakeResponse(json_body={"data": [{"b64_json": b64}]})

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    provider = _provider(Operation.IMAGE_TO_IMAGE.value, model="some-other-image")
    result = provider.submit(
        _request(Operation.IMAGE_TO_IMAGE.value, reference_object_keys=[reference_key])
    )

    assert result.succeeded is True
    assert [url for url, _ in calls] == ["/v1/images/generations"]
    assert "quality" not in calls[0][1]["json"]
    assert "files" not in calls[0][1]


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
    result = provider.submit(_request(Operation.IMAGE_TO_IMAGE.value, reference_object_keys=keys))

    assert result.succeeded is True
    assert len(calls[0]["input"]["image"]) == 3


def test_qwen_image_edit_missing_output_url_is_a_provider_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reference_key = "test/reference-for-qwen-edit-missing.png"
    s3.put_object(reference_key, base64.b64decode(_png_b64((4, 4, 4))), content_type="image/png")

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
    s3.put_object(reference_key, base64.b64decode(_png_b64((1, 2, 3))), content_type="image/png")
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
    monkeypatch.setattr(s3, "presign_get", lambda key, **kwargs: f"https://signed.invalid/{key}")
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
            json_body={
                "choices": [
                    {"message": {"content": f"```json\n{__import__('json').dumps(body)}\n```"}}
                ]
            }
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
    assert "extra" not in payloads[0]
    assert "extra_body" not in payloads[0]
    assert "frame_images" not in payloads[0]
    assert [item["frame_type"] for item in payloads[1]["frame_images"]] == [
        "first_frame",
        "last_frame",
    ]
    assert "input_references" not in payloads[1]


def test_wan_videoedit_with_refs_uses_openai_extra_body_media(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two live failures on the MiniMax facade, then one live complete
    on `/v1/videos` (2026-08-29): `input_references.type=video` is a
    create 400; `video_url` create-succeeds then Wan rejects
    `input.media.0.type`; `/ai/v1/videos` `extra` is ignored.
    `extra_body.input.media` with Wan's enum is the shape that finished."""
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        s3,
        "presign_get",
        lambda key, **kwargs: f"https://signed.invalid/{key}",
    )

    def fake_post(self, url, **kwargs):  # type: ignore[no-untyped-def]
        captured["url"] = url
        captured["json"] = kwargs["json"]
        return _FakeResponse(json_body={"id": "video_wan_edit"})

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    provider = _provider(Operation.VIDEO_TO_VIDEO.value, model="wan2.7-videoedit")
    result = provider.submit(
        _request(
            Operation.VIDEO_TO_VIDEO.value,
            duration_seconds=8,
            references=[
                ProviderReference(object_key="source.mp4", media_type="video"),
                ProviderReference(object_key="style.png", media_type="image"),
            ],
        )
    )

    assert captured["url"] == "/v1/videos"
    body = captured["json"]
    assert body["model"] == "wan2.7-videoedit"
    assert body["seconds"] == 8
    assert "input_references" not in body
    assert "input_reference" not in body
    assert "extra" not in body
    assert body["extra_body"]["input"]["media"] == [
        {"type": "video", "url": "https://signed.invalid/source.mp4"},
        {"type": "reference_image", "url": "https://signed.invalid/style.png"},
    ]
    assert result.pending is True
    assert result.external_task_id == "video_wan_edit"


def test_wan_videoedit_with_refs_polls_the_openai_video_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A task created on `/v1/videos` is 404 on `/ai/v1/tasks/{id}`
    (live 2026-08-29). Poll must stay on the OpenAI retrieve path even
    when the endpoint's configured protocol is still `minimax`."""

    def fake_get(self, url, **kwargs):  # type: ignore[no-untyped-def]
        assert url == "/v1/videos/video_wan_edit"
        return _FakeResponse(json_body={"status": "in_progress"})

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    provider = _provider(Operation.VIDEO_TO_VIDEO.value, model="wan2.7-videoedit")
    result = provider.poll(
        "video_wan_edit",
        _request(
            Operation.VIDEO_TO_VIDEO.value,
            references=[ProviderReference(object_key="source.mp4", media_type="video")],
        ),
    )

    assert result.pending is True
    assert result.succeeded is False


def test_h3_resolution_passthrough_defaults_to_2k_but_honours_768p(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payloads: list[dict] = []

    def fake_post(self, url, **kwargs):  # type: ignore[no-untyped-def]
        payloads.append(kwargs["json"])
        return _FakeResponse(json_body={"id": f"task-{len(payloads)}"})

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    provider = _provider(Operation.TEXT_TO_VIDEO.value, model="minimax-h3")
    provider.submit(_request(Operation.TEXT_TO_VIDEO.value, duration_seconds=5))
    provider.submit(_request(Operation.TEXT_TO_VIDEO.value, duration_seconds=5, resolution="768P"))

    assert payloads[0]["resolution"] == "2K"
    assert payloads[1]["resolution"] == "768P"


def test_h3_accepts_the_adaptive_aspect_ratio(monkeypatch: pytest.MonkeyPatch) -> None:
    payloads: list[dict] = []

    def fake_post(self, url, **kwargs):  # type: ignore[no-untyped-def]
        payloads.append(kwargs["json"])
        return _FakeResponse(json_body={"id": "task-1"})

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    provider = _provider(Operation.TEXT_TO_VIDEO.value, model="minimax-h3")
    result = provider.submit(
        _request(Operation.TEXT_TO_VIDEO.value, duration_seconds=5, aspect_ratio="adaptive")
    )

    assert result.pending is True
    assert payloads[0]["aspect_ratio"] == "adaptive"


def test_wan_videoedit_profile_rejects_a_duration_h3_would_accept(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`wan2.7-videoedit`'s own profile is 2-10 seconds, narrower than H3's
    4-15 — the per-model table, not a single shared constant, is what must
    reject 12 seconds here."""

    def fail_post(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("must not reach the network on a validation failure")

    monkeypatch.setattr(httpx.Client, "post", fail_post)
    provider = _provider(Operation.VIDEO_TO_VIDEO.value, model="wan2.7-videoedit")

    with pytest.raises(ValueError, match="duration must be between 2 and 10"):
        provider.submit(_request(Operation.VIDEO_TO_VIDEO.value, duration_seconds=12))
    with pytest.raises(ValueError, match="duration must be between 2 and 10"):
        provider.submit(
            _request(
                Operation.VIDEO_TO_VIDEO.value,
                duration_seconds=12,
                references=[ProviderReference(object_key="source.mp4", media_type="video")],
            )
        )


def test_wan_videoedit_profile_has_no_default_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unlike H3, `wan2.7-videoedit`'s schema has no documented default —
    omitting the field entirely (not fabricating one) is the correct
    passthrough when the caller doesn't specify a resolution."""
    payloads: list[dict] = []

    def fake_post(self, url, **kwargs):  # type: ignore[no-untyped-def]
        payloads.append(kwargs["json"])
        return _FakeResponse(json_body={"id": "task-1"})

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    provider = _provider(Operation.VIDEO_TO_VIDEO.value, model="wan2.7-videoedit")
    provider.submit(_request(Operation.VIDEO_TO_VIDEO.value, duration_seconds=8))

    assert "resolution" not in payloads[0]


def test_wan_videoedit_profile_honours_an_explicit_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payloads: list[dict] = []

    def fake_post(self, url, **kwargs):  # type: ignore[no-untyped-def]
        payloads.append(kwargs["json"])
        return _FakeResponse(json_body={"id": "task-1"})

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    provider = _provider(Operation.VIDEO_TO_VIDEO.value, model="wan2.7-videoedit")
    provider.submit(
        _request(Operation.VIDEO_TO_VIDEO.value, duration_seconds=8, resolution="1080p")
    )

    assert payloads[0]["resolution"] == "1080p"


def test_wan_videoedit_profile_rejects_an_unsupported_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_post(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("must not reach the network on a validation failure")

    monkeypatch.setattr(httpx.Client, "post", fail_post)
    provider = _provider(Operation.VIDEO_TO_VIDEO.value, model="wan2.7-videoedit")

    with pytest.raises(ValueError, match="resolution is unsupported: 2K"):
        provider.submit(
            _request(Operation.VIDEO_TO_VIDEO.value, duration_seconds=8, resolution="2K")
        )


def test_a_model_with_no_profile_gets_unopinionated_passthrough(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No registered `NativeVideoModelProfile` means no range validation and
    no fabricated `resolution` field — the behaviour `build_video_payload`
    always had before H3 became its first caller."""
    payloads: list[dict] = []

    def fake_post(self, url, **kwargs):  # type: ignore[no-untyped-def]
        payloads.append(kwargs["json"])
        return _FakeResponse(json_body={"id": "task-1"})

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    provider = _provider(Operation.TEXT_TO_VIDEO.value, model="some-unlisted-model")
    result = provider.submit(
        _request(Operation.TEXT_TO_VIDEO.value, duration_seconds=99, aspect_ratio="7:3")
    )

    assert result.pending is True
    assert "resolution" not in payloads[0]
    assert payloads[0]["duration"] == 99
    assert payloads[0]["aspect_ratio"] == "7:3"


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


def test_openai_video_submit_posts_to_v1_videos_without_a_reference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_post(self, url, **kwargs):  # type: ignore[no-untyped-def]
        captured["url"] = url
        captured["json"] = kwargs["json"]
        return _FakeResponse(json_body={"id": "video_123"})

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    provider = _provider(Operation.TEXT_TO_VIDEO.value, model="wan2.7-videoedit", protocol="openai")
    result = provider.submit(_request(Operation.TEXT_TO_VIDEO.value, duration_seconds=8))

    assert captured["url"] == "/v1/videos"
    assert captured["json"] == {
        "model": "wan2.7-videoedit",
        "prompt": "一只在雨夜霓虹街道上奔跑的机械狐狸",
        "seconds": 8,
    }
    assert result.pending is True
    assert result.external_task_id == "video_123"


def test_openai_video_submit_attaches_an_image_reference_when_supplied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(s3, "presign_get", lambda key, **kwargs: f"https://signed.invalid/{key}")
    captured: dict[str, object] = {}

    def fake_post(self, url, **kwargs):  # type: ignore[no-untyped-def]
        captured["json"] = kwargs["json"]
        return _FakeResponse(json_body={"id": "video_456"})

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    provider = _provider(
        Operation.TEXT_TO_VIDEO.value, model="some-openai-model", protocol="openai"
    )
    provider.submit(
        _request(
            Operation.TEXT_TO_VIDEO.value,
            references=[ProviderReference(object_key="ref.png", media_type="image")],
        )
    )

    assert captured["json"]["input_reference"] == {"image_url": "https://signed.invalid/ref.png"}


def test_openai_video_submit_missing_task_id_is_a_provider_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_post(self, url, **kwargs):  # type: ignore[no-untyped-def]
        return _FakeResponse(json_body={})

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    provider = _provider(Operation.TEXT_TO_VIDEO.value, model="wan2.7-videoedit", protocol="openai")
    result = provider.submit(_request(Operation.TEXT_TO_VIDEO.value))

    assert result.succeeded is False
    assert result.failure_code == "PROVIDER_INVALID_RESPONSE"


def test_openai_video_poll_stays_pending_and_reports_a_wobbly_progress_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Confirmed live against `wan2.7-videoedit`'s openai-shaped endpoint:
    its real status vocabulary is `queued`/`processing`/`completed`/`failed`
    — not the generic OpenAI docs' `in_progress` — so exclusion, not an
    allow-list, is what must keep this pending."""

    def fake_get(self, url, **kwargs):  # type: ignore[no-untyped-def]
        assert url == "/v1/videos/video_789"
        return _FakeResponse(json_body={"status": "processing", "progress": 42})

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    provider = _provider(Operation.TEXT_TO_VIDEO.value, model="wan2.7-videoedit", protocol="openai")
    result = provider.poll("video_789", _request(Operation.TEXT_TO_VIDEO.value))

    assert result.pending is True
    assert result.succeeded is False
    assert result.metadata["progress"] == 42


def test_openai_video_poll_downloads_the_finished_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    video_bytes = b"openai-mp4-bytes"

    def fake_get(self, url, **kwargs):  # type: ignore[no-untyped-def]
        if url.endswith("/content"):
            return _FakeResponse(content=video_bytes)
        return _FakeResponse(json_body={"status": "completed"})

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    provider = _provider(Operation.TEXT_TO_VIDEO.value, model="wan2.7-videoedit", protocol="openai")
    request = _request(Operation.TEXT_TO_VIDEO.value, duration_seconds=8)
    result = provider.poll("video_999", request)

    assert result.succeeded is True
    assert result.mime_type == "video/mp4"
    assert result.duration_ms == 8_000
    assert s3.get_object(result.object_key) == video_bytes


def test_openai_video_poll_reports_a_failed_task(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get(self, url, **kwargs):  # type: ignore[no-untyped-def]
        return _FakeResponse(json_body={"status": "failed", "error": "上游拒绝"})

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    provider = _provider(Operation.TEXT_TO_VIDEO.value, model="wan2.7-videoedit", protocol="openai")
    result = provider.poll("video_bad", _request(Operation.TEXT_TO_VIDEO.value))

    assert result.pending is False
    assert result.succeeded is False
    assert result.failure_code == "PROVIDER_TASK_FAILED"


def test_openai_video_cancel_always_returns_false(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_post(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("must not call an undocumented cancel endpoint")

    monkeypatch.setattr(httpx.Client, "post", fail_post)
    provider = _provider(Operation.TEXT_TO_VIDEO.value, model="wan2.7-videoedit", protocol="openai")

    assert provider.cancel("video_1") is False


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
        join_media_url("https://aihubmix.com", "/ai/v1/videos")
        == "https://aihubmix.com/ai/v1/videos"
    )
    assert media_request_path("https://proxy.example/openai/v1", "/v1/images/generations") == (
        "/openai/v1/images/generations"
    )
    # A native path on a `/v1`-suffixed openai base must not become `/v1/ai/v1/…`.
    assert media_request_path("https://aihubmix.com/v1", "/ai/v1/images/generations") == (
        "/ai/v1/images/generations"
    )
    assert media_request_path("https://aihubmix.com/v1/", "/ai/v1/images/task_1") == (
        "/ai/v1/images/task_1"
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
        model="doubao-seedream-4-0",
        base_url="https://aihubmix.com/v1",
        api_key="test-key",
        timeout_ms=5_000,
    )
    result = provider.submit(_request(Operation.TEXT_TO_IMAGE.value, quality_tier="preview"))

    assert result.succeeded is True
    assert captured["base"] == "https://aihubmix.com"
    assert captured["url"] == "/v1/images/generations"
    assert captured["size"] == "1024x576"


def test_qwen_image_3_on_a_v1_suffixed_base_posts_to_the_host_root_ai_v1_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, str] = {}
    b64 = _png_b64()

    def fake_post(self, url, **kwargs):  # type: ignore[no-untyped-def]
        captured["base"] = str(self.base_url).rstrip("/")
        captured["url"] = url
        captured["size"] = kwargs["json"]["size"]
        return _FakeResponse(
            json_body={"id": "task_1", "status": "completed", "output": [{"b64_json": b64}]}
        )

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
    assert captured["url"] == "/ai/v1/images/generations"
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


def test_http_4xx_logs_the_redacted_upstream_body(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def fake_post(self, url, **kwargs):  # type: ignore[no-untyped-def]
        request = httpx.Request("POST", "https://aihubmix.invalid/v1/images/generations")
        return httpx.Response(
            400,
            text='{"error":{"code":"schema_violation","message":"bad size; key test-key"}}',
            request=request,
        )

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    with caplog.at_level("WARNING", logger="app.providers.aihubmix_media"):
        _provider(Operation.TEXT_TO_IMAGE.value).submit(_request(Operation.TEXT_TO_IMAGE.value))

    assert "HTTP 400" in caplog.text
    assert "schema_violation" in caplog.text
    assert "test-key" not in caplog.text


# -- qwen-image-3.0: native `/ai/v1/images/generations` media task (sync) --


def _image_task(status: str = "completed", **fields: object) -> dict[str, object]:
    task: dict[str, object] = {
        "id": "task_img_1",
        "object": "image",
        "model": "qwen-image-3.0",
        "status": status,
        "output": [],
        "error": None,
    }
    task.update(fields)
    return task


def test_qwen_image_3_text_to_image_uses_the_ai_v1_media_task_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    png = base64.b64decode(_png_b64(size=(40, 30)))
    content_url = "https://aihubmix.invalid/ai/v1/images/task_img_1/content/result_1"
    posts: list[tuple[str, dict[str, object]]] = []
    gets: list[tuple[str, str | None, dict[str, object]]] = []

    def fake_post(self, url, **kwargs):  # type: ignore[no-untyped-def]
        posts.append((url, kwargs))
        return _FakeResponse(
            json_body=_image_task(output=[{"index": 0, "type": "file", "content_url": content_url}])
        )

    def fake_get(self, url, **kwargs):  # type: ignore[no-untyped-def]
        gets.append((url, self.headers.get("Authorization"), kwargs))
        return _FakeResponse(content=png)

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    monkeypatch.setattr(httpx.Client, "get", fake_get)
    result = _provider(Operation.TEXT_TO_IMAGE.value, model="qwen-image-3.0").submit(
        _request(
            Operation.TEXT_TO_IMAGE.value,
            aspect_ratio="9:16",
            seed=42,
            negative_prompt="模糊, 水印",
        )
    )

    assert result.succeeded is True
    assert result.pending is False
    assert (result.width, result.height) == (40, 30)
    assert s3.get_object(result.object_key) == png
    assert result.metadata["endpoint"] == "ai-v1-images"
    assert result.metadata["upstream_task_id"] == "task_img_1"
    assert [url for url, _ in posts] == ["/ai/v1/images/generations"]
    assert posts[0][1]["json"] == {
        "model": "qwen-image-3.0",
        "prompt": "一只在雨夜霓虹街道上奔跑的机械狐狸",
        "size": "576x1024",
        "n": 1,
        "seed": 42,
        "negative_prompt": "模糊, 水印",
    }
    # AiHubMix's own content URL needs the Bearer token.
    assert gets == [(content_url, "Bearer test-key", {"follow_redirects": True})]


def test_qwen_image_3_decodes_inline_b64_output(monkeypatch: pytest.MonkeyPatch) -> None:
    b64 = _png_b64()

    def fake_post(self, url, **kwargs):  # type: ignore[no-untyped-def]
        return _FakeResponse(json_body=_image_task(output=[{"index": 0, "b64_json": b64}]))

    def fail_get(self, url, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("inline b64 output must not trigger a download")

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    monkeypatch.setattr(httpx.Client, "get", fail_get)
    result = _provider(Operation.TEXT_TO_IMAGE.value, model="qwen-image-3.0").submit(
        _request(Operation.TEXT_TO_IMAGE.value)
    )

    assert result.succeeded is True
    assert s3.get_object(result.object_key) == base64.b64decode(b64)


def test_qwen_image_3_tolerates_an_openai_data_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    b64 = _png_b64()

    def fake_post(self, url, **kwargs):  # type: ignore[no-untyped-def]
        return _FakeResponse(json_body={"created": 1, "data": [{"b64_json": b64}]})

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    result = _provider(Operation.TEXT_TO_IMAGE.value, model="qwen-image-3.0").submit(
        _request(Operation.TEXT_TO_IMAGE.value)
    )

    assert result.succeeded is True
    assert s3.get_object(result.object_key) == base64.b64decode(b64)


def test_qwen_image_3_offsite_content_url_is_downloaded_without_the_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    png = base64.b64decode(_png_b64())
    auth_headers: list[str | None] = []

    def fake_post(self, url, **kwargs):  # type: ignore[no-untyped-def]
        return _FakeResponse(
            json_body=_image_task(output=[{"content_url": "https://oss.invalid/out.png?sig=1"}])
        )

    def fake_get(self, url, **kwargs):  # type: ignore[no-untyped-def]
        auth_headers.append(self.headers.get("Authorization"))
        return _FakeResponse(content=png)

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    monkeypatch.setattr(httpx.Client, "get", fake_get)
    result = _provider(Operation.TEXT_TO_IMAGE.value, model="qwen-image-3.0").submit(
        _request(Operation.TEXT_TO_IMAGE.value)
    )

    assert result.succeeded is True
    assert auth_headers == [None]


def test_qwen_image_3_failed_task_is_a_terminal_provider_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_post(self, url, **kwargs):  # type: ignore[no-untyped-def]
        return _FakeResponse(
            json_body=_image_task(
                "failed",
                error={"code": "output_blocked", "message": "The model provider blocked it."},
            )
        )

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    result = _provider(Operation.TEXT_TO_IMAGE.value, model="qwen-image-3.0").submit(
        _request(Operation.TEXT_TO_IMAGE.value)
    )

    assert result.succeeded is False
    assert result.pending is False
    assert result.failure_code == "PROVIDER_TASK_FAILED"
    assert result.metadata["detail"] == "output_blocked: The model provider blocked it."


def test_qwen_image_3_polls_the_image_task_when_the_sync_call_returns_early(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.providers import aihubmix_media

    b64 = _png_b64()
    gets: list[str] = []
    replies = iter(
        [
            _image_task("in_progress"),
            _image_task(output=[{"b64_json": b64}]),
        ]
    )

    def fake_post(self, url, **kwargs):  # type: ignore[no-untyped-def]
        return _FakeResponse(json_body=_image_task("pending"))

    def fake_get(self, url, **kwargs):  # type: ignore[no-untyped-def]
        gets.append(url)
        return _FakeResponse(json_body=next(replies))

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    monkeypatch.setattr(httpx.Client, "get", fake_get)
    monkeypatch.setattr(aihubmix_media.time, "sleep", lambda seconds: None)
    result = _provider(Operation.TEXT_TO_IMAGE.value, model="qwen-image-3.0").submit(
        _request(Operation.TEXT_TO_IMAGE.value)
    )

    assert result.succeeded is True
    assert gets == ["/ai/v1/images/task_img_1", "/ai/v1/images/task_img_1"]


def test_qwen_image_3_unfinished_task_past_the_timeout_is_a_temporary_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_post(self, url, **kwargs):  # type: ignore[no-untyped-def]
        return _FakeResponse(json_body=_image_task("in_progress"))

    def fail_get(self, url, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("no budget left to poll")

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    monkeypatch.setattr(httpx.Client, "get", fail_get)
    provider = AiHubMixMediaProvider(
        endpoint_id="ep-test",
        capability_tag=Operation.TEXT_TO_IMAGE.value,
        model="qwen-image-3.0",
        base_url="https://aihubmix.invalid",
        api_key="test-key",
        timeout_ms=0,
    )
    result = provider.submit(_request(Operation.TEXT_TO_IMAGE.value))

    assert result.succeeded is False
    assert result.failure_code == "PROVIDER_TEMPORARY_FAILURE"
    assert "task_img_1 still in_progress" in result.metadata["detail"]


def test_a_legacy_protocol_rejection_retries_once_on_the_ai_v1_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A model AiHubMix migrates later must not silently fail for weeks the
    way qwen-image-3.0 did: the documented rejection switches protocols."""
    b64 = _png_b64()
    posts: list[tuple[str, dict[str, object]]] = []

    def fake_post(self, url, **kwargs):  # type: ignore[no-untyped-def]
        posts.append((url, kwargs))
        if url == "/v1/images/generations":
            return httpx.Response(
                400,
                json={
                    "error": {
                        "code": "protocol_not_supported",
                        "message": "This model does not support the legacy protocol. "
                        "Use POST /ai/v1/images/generations.",
                    }
                },
                request=httpx.Request("POST", f"https://aihubmix.invalid{url}"),
            )
        return _FakeResponse(json_body=_image_task(output=[{"b64_json": b64}]))

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    result = _provider(Operation.TEXT_TO_IMAGE.value, model="qwen-image-9.0").submit(
        _request(Operation.TEXT_TO_IMAGE.value)
    )

    assert result.succeeded is True
    assert [url for url, _ in posts] == ["/v1/images/generations", "/ai/v1/images/generations"]
    assert posts[1][1]["json"]["model"] == "qwen-image-9.0"
    assert result.metadata["endpoint"] == "ai-v1-images"


def test_gpt_image_2_never_takes_the_ai_v1_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    posts: list[str] = []

    def fake_post(self, url, **kwargs):  # type: ignore[no-untyped-def]
        posts.append(url)
        return httpx.Response(
            400,
            json={"error": {"code": "protocol_not_supported", "message": "legacy"}},
            request=httpx.Request("POST", f"https://aihubmix.invalid{url}"),
        )

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    result = _provider(Operation.TEXT_TO_IMAGE.value, model="gpt-image-2").submit(
        _request(Operation.TEXT_TO_IMAGE.value)
    )

    assert result.failure_code == "PROVIDER_INVALID_RESPONSE"
    assert posts == ["/v1/images/generations"]


# -- doubao-seedance-2-5-260628: auto-duration, generate_audio, inline poll --


def test_seedance_25_accepts_the_auto_duration_sentinel(monkeypatch: pytest.MonkeyPatch) -> None:
    payloads: list[dict] = []

    def fake_post(self, url, **kwargs):  # type: ignore[no-untyped-def]
        payloads.append(kwargs["json"])
        return _FakeResponse(json_body={"id": "task-1"})

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    provider = _provider(Operation.TEXT_TO_VIDEO.value, model="doubao-seedance-2-5-260628")
    result = provider.submit(
        _request(Operation.TEXT_TO_VIDEO.value, duration_seconds=-1, aspect_ratio="adaptive")
    )

    assert result.pending is True
    assert payloads[0]["duration"] == -1
    assert payloads[0]["resolution"] == "720p"


def test_seedance_25_rejects_an_explicit_duration_outside_its_own_range(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_post(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("must not reach the network on a validation failure")

    monkeypatch.setattr(httpx.Client, "post", fail_post)
    provider = _provider(Operation.TEXT_TO_VIDEO.value, model="doubao-seedance-2-5-260628")

    with pytest.raises(ValueError, match="duration must be between 4 and 30"):
        provider.submit(_request(Operation.TEXT_TO_VIDEO.value, duration_seconds=45))


def test_seedance_25_forwards_generate_audio_when_the_caller_sets_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payloads: list[dict] = []

    def fake_post(self, url, **kwargs):  # type: ignore[no-untyped-def]
        payloads.append(kwargs["json"])
        return _FakeResponse(json_body={"id": "task-1"})

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    provider = _provider(Operation.TEXT_TO_VIDEO.value, model="doubao-seedance-2-5-260628")
    provider.submit(
        _request(Operation.TEXT_TO_VIDEO.value, duration_seconds=6, extra={"generate_audio": False})
    )

    assert payloads[0]["generate_audio"] is False


def test_seedance_25_omits_generate_audio_when_the_caller_does_not_set_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payloads: list[dict] = []

    def fake_post(self, url, **kwargs):  # type: ignore[no-untyped-def]
        payloads.append(kwargs["json"])
        return _FakeResponse(json_body={"id": "task-1"})

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    provider = _provider(Operation.TEXT_TO_VIDEO.value, model="doubao-seedance-2-5-260628")
    provider.submit(_request(Operation.TEXT_TO_VIDEO.value, duration_seconds=6))

    assert "generate_audio" not in payloads[0]


def test_seedance_25_polls_ai_v1_videos_not_ai_v1_tasks(monkeypatch: pytest.MonkeyPatch) -> None:
    """Its schema documents `poll_path: /ai/v1/videos/{id}`, not the H3/
    wan2.7-videoedit `/ai/v1/tasks/{id}` pair — see `NativeVideoModelProfile
    .poll_style`."""
    requested: list[str] = []

    def fake_get(self, url, **kwargs):  # type: ignore[no-untyped-def]
        requested.append(url)
        return _FakeResponse(json_body={"status": "in_progress"})

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    provider = _provider(Operation.TEXT_TO_VIDEO.value, model="doubao-seedance-2-5-260628")
    result = provider.poll("task-seedance-1", _request(Operation.TEXT_TO_VIDEO.value))

    assert requested == ["/ai/v1/videos/task-seedance-1"]
    assert result.pending is True


def test_seedance_25_downloads_a_completed_inline_video_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    video_bytes = b"seedance-mp4-bytes"
    video_url = "https://ark-acg-cn-beijing.tos-cn-beijing.volces.com/seedance-output.mp4"

    def fake_get(self, url, **kwargs):  # type: ignore[no-untyped-def]
        if url == "/ai/v1/videos/task-seedance-2":
            return _FakeResponse(
                json_body={
                    "status": "completed",
                    "output": [
                        {"type": "message", "content": [{"type": "output_text", "text": video_url}]}
                    ],
                }
            )
        assert url == video_url
        return _FakeResponse(content=video_bytes)

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    provider = _provider(Operation.TEXT_TO_VIDEO.value, model="doubao-seedance-2-5-260628")
    result = provider.poll(
        "task-seedance-2", _request(Operation.TEXT_TO_VIDEO.value, duration_seconds=5)
    )

    assert result.succeeded is True
    assert result.mime_type == "video/mp4"
    assert result.duration_ms == 5_000
    assert s3.get_object(result.object_key) == video_bytes


def test_seedance_25_reports_a_failed_task(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get(self, url, **kwargs):  # type: ignore[no-untyped-def]
        return _FakeResponse(json_body={"status": "failed", "error": "content_flagged"})

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    provider = _provider(Operation.TEXT_TO_VIDEO.value, model="doubao-seedance-2-5-260628")
    result = provider.poll("task-seedance-3", _request(Operation.TEXT_TO_VIDEO.value))

    assert result.succeeded is False
    assert result.failure_code == "PROVIDER_TASK_FAILED"


def test_seedance_25_cancel_is_unsupported(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_post(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("must not call cancel")

    monkeypatch.setattr(httpx.Client, "post", fail_post)
    provider = _provider(Operation.TEXT_TO_VIDEO.value, model="doubao-seedance-2-5-260628")
    assert provider.cancel("task-1") is False


@pytest.mark.parametrize(("model", "expected"), [("tts-1-hd", 0.25), ("gpt-4o-mini-tts", None)])
def test_audio_speed_is_forwarded_only_for_tts_1(
    monkeypatch: pytest.MonkeyPatch, model: str, expected: float | None
) -> None:
    def fake_post(self, url, **kwargs):  # type: ignore[no-untyped-def]
        assert kwargs["json"].get("speed") == expected
        return _FakeResponse(content=b"bytes")

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    provider = _provider(Operation.AUDIO_GENERATION.value, model)
    result = provider.submit(
        _request(Operation.AUDIO_GENERATION.value, extra={"voice": "nova", "speed": 0.1})
    )
    assert result.succeeded is True
