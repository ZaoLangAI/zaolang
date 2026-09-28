"""DMXAPI media provider: request-body construction, task-id/status
extraction, and the submit/poll HTTP contract for both the synchronous
image family and the submit-task-then-poll video families.
"""

from __future__ import annotations

import httpx
import pytest

from app.models.enums import Operation
from app.providers.base import GenerationRequest, ProviderReference
from app.providers.dmxapi_media import (
    AUDIO_MODEL_GPT4O_MINI_TTS,
    AUDIO_MODEL_TTS_PRO,
    DOUBAO_SEEDANCE_25_MODEL,
    MINIMAX_H3_MODEL,
    MINIMAX_H3_REGENERATION_MODEL,
    MUSIC_MODEL_DMX,
    SEEDREAM_5_PRO_MODEL,
    WAN3_VIDEO_MODEL,
    DmxApiMediaProvider,
    _build_minimax_h3_body,
    _build_minimax_h3_regeneration_body,
    _build_music_body,
    _build_seedance_25_video_body,
    _build_seedream_body,
    _build_wan3_body,
    extract_music_result,
    extract_seedream_result,
    extract_task_id,
    image_model_profile,
    probe_music_body,
    video_model_profile,
)
from app.storage import s3


def _provider(capability_tag: str, model: str) -> DmxApiMediaProvider:
    return DmxApiMediaProvider(
        endpoint_id="ep-dmx",
        capability_tag=capability_tag,
        model=model,
        base_url="https://www.dmxapi.cn",
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
    def __init__(self, *, json_body: dict | None = None, content: bytes = b"") -> None:
        self._json_body = json_body
        self.content = content
        self.status_code = 200

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        assert self._json_body is not None
        return self._json_body


# -- profile tables -----------------------------------------------------------


def test_every_video_model_has_a_profile() -> None:
    for model in (
        MINIMAX_H3_MODEL,
        MINIMAX_H3_REGENERATION_MODEL,
        DOUBAO_SEEDANCE_25_MODEL,
        WAN3_VIDEO_MODEL,
    ):
        assert video_model_profile(model) is not None


def test_the_seedream_image_model_has_a_profile() -> None:
    profile = image_model_profile(SEEDREAM_5_PRO_MODEL)
    assert profile is not None
    assert profile.max_reference_count == 10


# -- request builders: MiniMax-H3 --------------------------------------------


def test_minimax_h3_text_to_video_body() -> None:
    body = _build_minimax_h3_body(_request(Operation.TEXT_TO_VIDEO.value, duration_seconds=5))
    assert body["model"] == MINIMAX_H3_MODEL
    assert body["input"] == [{"type": "text", "text": "一只在雨夜霓虹街道上奔跑的机械狐狸"}]
    assert body["duration"] == 5
    assert body["ratio"] == "16:9"
    assert body["resolution"] == "2K"


def test_minimax_h3_rejects_an_out_of_range_duration() -> None:
    with pytest.raises(ValueError, match="duration must be between 4 and 15"):
        _build_minimax_h3_body(_request(Operation.TEXT_TO_VIDEO.value, duration_seconds=20))


def test_minimax_h3_first_last_frame_roles(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(s3, "presign_get", lambda key, **kwargs: f"https://signed.invalid/{key}")
    body = _build_minimax_h3_body(
        _request(
            Operation.IMAGE_TO_VIDEO.value,
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
    items = body["input"]
    assert items[0] == {"type": "text", "text": "一只在雨夜霓虹街道上奔跑的机械狐狸"}
    assert items[1] == {
        "type": "image_url",
        "image_url": {"url": "https://signed.invalid/first.png"},
        "role": "first_frame",
    }
    assert items[2]["role"] == "last_frame"


def test_minimax_h3_generic_reference_gets_a_reference_role(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(s3, "presign_get", lambda key, **kwargs: f"https://signed.invalid/{key}")
    body = _build_minimax_h3_body(
        _request(
            Operation.VIDEO_TO_VIDEO.value,
            references=[ProviderReference(object_key="ref.mp4", media_type="video")],
        )
    )
    ref_item = body["input"][1]
    assert ref_item["type"] == "video_url"
    assert ref_item["role"] == "reference_video"


# -- request builders: MiniMax-H3 video regeneration -------------------------


def test_regeneration_requires_a_base_video_reference() -> None:
    with pytest.raises(ValueError, match="base_video"):
        _build_minimax_h3_regeneration_body(_request(Operation.VIDEO_TO_VIDEO.value))


def test_regeneration_body_carries_the_original_prompt_and_base_video(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(s3, "presign_get", lambda key, **kwargs: f"https://signed.invalid/{key}")
    body = _build_minimax_h3_regeneration_body(
        _request(
            Operation.VIDEO_TO_VIDEO.value,
            references=[
                ProviderReference(
                    object_key="source.mp4", media_type="video", frame_type="base_video"
                )
            ],
        )
    )
    assert body["model"] == MINIMAX_H3_REGENERATION_MODEL
    assert body["input"] == [
        {"type": "text", "text": "一只在雨夜霓虹街道上奔跑的机械狐狸"},
        {
            "type": "video_url",
            "video_url": {"url": "https://signed.invalid/source.mp4"},
            "role": "base_video",
        },
    ]


# -- request builders: doubao-seedance-2-5-260628 (video) --------------------


def test_seedance_25_video_defaults_resolution_and_supports_auto_duration() -> None:
    body = _build_seedance_25_video_body(
        _request(Operation.TEXT_TO_VIDEO.value, duration_seconds=-1, aspect_ratio="adaptive")
    )
    assert body["model"] == DOUBAO_SEEDANCE_25_MODEL
    assert body["duration"] == -1
    assert body["resolution"] == "720p"
    assert body["input"] == [{"type": "text", "text": "一只在雨夜霓虹街道上奔跑的机械狐狸"}]
    assert "input_references" not in body
    assert "frame_images" not in body


def test_seedance_25_multimodal_references_go_into_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(s3, "presign_get", lambda key, **kwargs: f"https://signed.invalid/{key}")
    body = _build_seedance_25_video_body(
        _request(
            Operation.IMAGE_TO_VIDEO.value,
            aspect_ratio="16:9",
            references=[
                ProviderReference(object_key="ref.png", media_type="image"),
                ProviderReference(object_key="ref.mp4", media_type="video"),
            ],
        )
    )
    assert body["ratio"] == "16:9"
    assert "input_references" not in body
    assert body["input"][0] == {"type": "text", "text": "一只在雨夜霓虹街道上奔跑的机械狐狸"}
    assert body["input"][1] == {
        "type": "image_url",
        "image_url": {"url": "https://signed.invalid/ref.png"},
        "role": "reference_image",
    }
    assert body["input"][2] == {
        "type": "video_url",
        "video_url": {"url": "https://signed.invalid/ref.mp4"},
        "role": "reference_video",
    }


def test_seedance_25_first_last_frame_go_into_input_with_adaptive_ratio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(s3, "presign_get", lambda key, **kwargs: f"https://signed.invalid/{key}")
    body = _build_seedance_25_video_body(
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
    assert "frame_images" not in body
    assert body["input"][1] == {
        "type": "image_url",
        "image_url": {"url": "https://signed.invalid/first.png"},
        "role": "first_frame",
    }
    assert body["input"][2]["role"] == "last_frame"


def test_seedance_25_video_frame_images_and_input_references_are_exclusive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(s3, "presign_get", lambda key, **kwargs: f"https://signed.invalid/{key}")
    with pytest.raises(ValueError, match="mutually exclusive"):
        _build_seedance_25_video_body(
            _request(
                Operation.IMAGE_TO_VIDEO.value,
                references=[
                    ProviderReference(
                        object_key="a.png", media_type="image", frame_type="first_frame"
                    ),
                    ProviderReference(object_key="b.mp4", media_type="video"),
                ],
            )
        )


# -- request builders: wan3.0-video ------------------------------------------


def test_wan3_requires_prompt_or_media() -> None:
    with pytest.raises(ValueError, match="requires a prompt or"):
        _build_wan3_body(_request(Operation.TEXT_TO_VIDEO.value, prompt=""))


def test_wan3_text_to_video_body() -> None:
    body = _build_wan3_body(_request(Operation.TEXT_TO_VIDEO.value, duration_seconds=5))
    assert body["model"] == WAN3_VIDEO_MODEL
    assert body["input"] == {"prompt": "一只在雨夜霓虹街道上奔跑的机械狐狸"}
    assert body["parameters"]["duration"] == 5
    assert body["parameters"]["resolution"] == "1080P"


def test_wan3_video_edit_uses_reference_video_role(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(s3, "presign_get", lambda key, **kwargs: f"https://signed.invalid/{key}")
    body = _build_wan3_body(
        _request(
            Operation.VIDEO_TO_VIDEO.value,
            prompt="将整个画面转换为黏土风格",
            duration_seconds=-1,
            aspect_ratio="adaptive",
            references=[ProviderReference(object_key="source.mp4", media_type="video")],
        )
    )
    assert body["input"]["media"] == [
        {"type": "reference_video", "url": "https://signed.invalid/source.mp4"}
    ]
    assert body["parameters"]["duration"] == -1


# -- request builders: doubao-seedream-5-0-pro-260628 (image) ----------------


def test_seedream_text_to_image_body() -> None:
    body = _build_seedream_body(_request(Operation.TEXT_TO_IMAGE.value))
    assert body["model"] == SEEDREAM_5_PRO_MODEL
    assert body["input"] == "一只在雨夜霓虹街道上奔跑的机械狐狸"
    assert "image" not in body
    assert body["size"] == "1424x800"  # 16:9 at the default (non-cinematic) 1K tier


def test_seedream_cinematic_tier_uses_2k_pixel_size() -> None:
    body = _build_seedream_body(_request(Operation.TEXT_TO_IMAGE.value, quality_tier="cinematic"))
    assert body["size"] == "2816x1584"


def test_seedream_multi_image_fusion(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(s3, "presign_get", lambda key, **kwargs: f"https://signed.invalid/{key}")
    body = _build_seedream_body(
        _request(
            Operation.IMAGE_TO_IMAGE.value,
            references=[
                ProviderReference(object_key="a.png", media_type="image"),
                ProviderReference(object_key="b.png", media_type="image"),
            ],
        )
    )
    assert body["image"] == ["https://signed.invalid/a.png", "https://signed.invalid/b.png"]


def test_seedream_single_reference_is_not_wrapped_in_a_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(s3, "presign_get", lambda key, **kwargs: f"https://signed.invalid/{key}")
    body = _build_seedream_body(
        _request(
            Operation.IMAGE_TO_IMAGE.value,
            references=[ProviderReference(object_key="a.png", media_type="image")],
        )
    )
    assert body["image"] == "https://signed.invalid/a.png"


# -- response parsing: task id / poll result ---------------------------------


def test_extract_task_id_minimax_h3() -> None:
    assert extract_task_id(MINIMAX_H3_MODEL, {"task_id": "427019898360251"}) == "427019898360251"


def test_extract_task_id_seedance() -> None:
    assert extract_task_id(DOUBAO_SEEDANCE_25_MODEL, {"id": "task_abc"}) == "task_abc"


def test_extract_task_id_wan3_from_provider_metadata() -> None:
    payload = {
        "output": [{"type": "message", "content": [{"type": "output_text", "text": "e47a17af"}]}],
        "provider_metadata": {"task_id": "e47a17af", "task_status": "PENDING"},
    }
    assert extract_task_id(WAN3_VIDEO_MODEL, payload) == "e47a17af"


def test_extract_seedream_result_from_data_entry() -> None:
    url, b64 = extract_seedream_result({"data": [{"url": "https://cdn.invalid/out.png"}]})
    assert url == "https://cdn.invalid/out.png"
    assert b64 is None


def test_extract_seedream_result_from_b64_json() -> None:
    url, b64 = extract_seedream_result({"data": [{"b64_json": "Zm9v"}]})
    assert url is None
    assert b64 == "Zm9v"


# -- provider submit()/poll(): video -----------------------------------------


def test_submit_minimax_h3_returns_pending_with_task_id(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_post(self, url, **kwargs):  # type: ignore[no-untyped-def]
        captured["url"] = url
        captured["json"] = kwargs["json"]
        return _FakeResponse(json_body={"task_id": "427019898360251", "usage": {}})

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    provider = _provider(Operation.TEXT_TO_VIDEO.value, MINIMAX_H3_MODEL)
    result = provider.submit(_request(Operation.TEXT_TO_VIDEO.value))

    assert captured["url"] == "/v1/responses"
    assert result.pending is True
    assert result.external_task_id == "427019898360251"


def test_submit_missing_task_id_is_a_provider_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_post(self, url, **kwargs):  # type: ignore[no-untyped-def]
        return _FakeResponse(json_body={"usage": {}})

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    provider = _provider(Operation.TEXT_TO_VIDEO.value, MINIMAX_H3_MODEL)
    result = provider.submit(_request(Operation.TEXT_TO_VIDEO.value))

    assert result.succeeded is False
    assert result.failure_code == "PROVIDER_INVALID_RESPONSE"


def test_poll_minimax_h3_downloads_the_finished_video(monkeypatch: pytest.MonkeyPatch) -> None:
    video_bytes = b"h3-mp4-bytes"
    video_url = "https://your-cdn.example.com/h3-generated-2k-output.mp4"

    def fake_post(self, url, **kwargs):  # type: ignore[no-untyped-def]
        assert kwargs["json"] == {"model": "MiniMax-H3-get", "input": "427019898360251"}
        return _FakeResponse(
            json_body={
                "task": {
                    "id": "427019898360251",
                    "status": "succeeded",
                    "content": {"url": video_url},
                }
            }
        )

    def fake_get(self, url, **kwargs):  # type: ignore[no-untyped-def]
        assert url == video_url
        return _FakeResponse(content=video_bytes)

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    monkeypatch.setattr(httpx.Client, "get", fake_get)
    provider = _provider(Operation.TEXT_TO_VIDEO.value, MINIMAX_H3_MODEL)
    result = provider.poll(
        "427019898360251", _request(Operation.TEXT_TO_VIDEO.value, duration_seconds=5)
    )

    assert result.succeeded is True
    assert result.mime_type == "video/mp4"
    assert s3.get_object(result.object_key) == video_bytes


def test_poll_minimax_h3_stays_pending_while_running(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_post(self, url, **kwargs):  # type: ignore[no-untyped-def]
        return _FakeResponse(json_body={"task": {"status": "running"}})

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    provider = _provider(Operation.TEXT_TO_VIDEO.value, MINIMAX_H3_MODEL)
    result = provider.poll("task-1", _request(Operation.TEXT_TO_VIDEO.value))

    assert result.pending is True
    assert result.succeeded is False


def _poll_error_response(
    status_code: int, *, json_body: dict | None = None, text: str = ""
) -> httpx.Response:
    request = httpx.Request("POST", "https://www.dmxapi.cn/v1/responses")
    if json_body is not None:
        return httpx.Response(status_code, json=json_body, request=request)
    return httpx.Response(status_code, text=text, request=request)


def test_poll_minimax_h3_upstream_error_502_is_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_post(self, url, **kwargs):  # type: ignore[no-untyped-def]
        return _poll_error_response(
            502,
            json_body={
                "error": {
                    "message": "MiniMax-H3 video generation task failed",
                    "type": "dmxapi_api_error",
                    "param": "input",
                    "code": "dmxapi_upstream_error",
                }
            },
        )

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    provider = _provider(Operation.TEXT_TO_VIDEO.value, MINIMAX_H3_MODEL)
    result = provider.poll("437661478302096", _request(Operation.TEXT_TO_VIDEO.value))

    assert result.pending is False
    assert result.succeeded is False
    assert result.failure_code == "PROVIDER_TASK_FAILED"
    assert result.metadata["detail"] == "MiniMax-H3 video generation task failed"


def test_poll_minimax_h3_empty_502_stays_pending(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_post(self, url, **kwargs):  # type: ignore[no-untyped-def]
        return _poll_error_response(502, text="")

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    provider = _provider(Operation.TEXT_TO_VIDEO.value, MINIMAX_H3_MODEL)
    result = provider.poll("task-empty-502", _request(Operation.TEXT_TO_VIDEO.value))

    assert result.pending is True
    assert result.succeeded is False
    assert result.failure_code is None


def test_poll_minimax_h3_read_timeout_stays_pending(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_post(self, url, **kwargs):  # type: ignore[no-untyped-def]
        raise httpx.ReadTimeout(
            "The read operation timed out",
            request=httpx.Request("POST", "https://www.dmxapi.cn/v1/responses"),
        )

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    provider = _provider(Operation.TEXT_TO_VIDEO.value, MINIMAX_H3_MODEL)
    result = provider.poll("task-timeout", _request(Operation.TEXT_TO_VIDEO.value))

    assert result.pending is True
    assert result.succeeded is False
    assert result.failure_code is None


def test_poll_seedance_downloads_the_finished_video(monkeypatch: pytest.MonkeyPatch) -> None:
    video_bytes = b"seedance-mp4-bytes"
    video_url = "https://ark-acg-cn-bejing.tos-cn-beijing.volces.com/out.mp4"

    def fake_post(self, url, **kwargs):  # type: ignore[no-untyped-def]
        assert kwargs["json"] == {"model": "seedance-2-5-get", "input": "task_8AA"}
        return _FakeResponse(
            json_body={
                "id": "task_8AA",
                "status": "succeeded",
                "output": [
                    {"type": "message", "content": [{"type": "output_text", "text": video_url}]}
                ],
            }
        )

    def fake_get(self, url, **kwargs):  # type: ignore[no-untyped-def]
        assert url == video_url
        return _FakeResponse(content=video_bytes)

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    monkeypatch.setattr(httpx.Client, "get", fake_get)
    provider = _provider(Operation.TEXT_TO_VIDEO.value, DOUBAO_SEEDANCE_25_MODEL)
    result = provider.poll("task_8AA", _request(Operation.TEXT_TO_VIDEO.value))

    assert result.succeeded is True
    assert s3.get_object(result.object_key) == video_bytes


def test_poll_wan3_infers_completion_from_the_url_shaped_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The one completed sample this research retrieved for `wan3.0-video`
    carried no top-level `status` field at all — only the final URL in
    `output[]` — so completion is inferred from that text looking like a
    URL (see `_poll_result`'s docstring)."""
    video_bytes = b"wan3-mp4-bytes"
    video_url = "https://dashscope-a717.oss-accelerate.aliyuncs.com/out.mp4"

    def fake_post(self, url, **kwargs):  # type: ignore[no-untyped-def]
        assert kwargs["json"] == {"model": "wan3.0-get", "input": "e47a17af"}
        return _FakeResponse(
            json_body={
                "output": [
                    {"type": "message", "content": [{"type": "output_text", "text": video_url}]}
                ],
                "request_id": "b7005146",
            }
        )

    def fake_get(self, url, **kwargs):  # type: ignore[no-untyped-def]
        assert url == video_url
        return _FakeResponse(content=video_bytes)

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    monkeypatch.setattr(httpx.Client, "get", fake_get)
    provider = _provider(Operation.TEXT_TO_VIDEO.value, WAN3_VIDEO_MODEL)
    result = provider.poll("e47a17af", _request(Operation.TEXT_TO_VIDEO.value))

    assert result.succeeded is True
    assert s3.get_object(result.object_key) == video_bytes


def test_poll_wan3_stays_pending_while_task_status_is_pending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_post(self, url, **kwargs):  # type: ignore[no-untyped-def]
        return _FakeResponse(
            json_body={
                "output": [
                    {"type": "message", "content": [{"type": "output_text", "text": "e47a17af"}]}
                ],
                "provider_metadata": {"task_id": "e47a17af", "task_status": "PENDING"},
            }
        )

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    provider = _provider(Operation.TEXT_TO_VIDEO.value, WAN3_VIDEO_MODEL)
    result = provider.poll("e47a17af", _request(Operation.TEXT_TO_VIDEO.value))

    assert result.pending is True
    assert result.succeeded is False


def test_regeneration_has_no_poll_style_gap_it_shares_h3s_poll_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_post(self, url, **kwargs):  # type: ignore[no-untyped-def]
        assert kwargs["json"]["model"] == "MiniMax-H3-get"
        return _FakeResponse(json_body={"task": {"status": "running"}})

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    provider = _provider(Operation.VIDEO_TO_VIDEO.value, MINIMAX_H3_REGENERATION_MODEL)
    result = provider.poll("task-regen-1", _request(Operation.VIDEO_TO_VIDEO.value))

    assert result.pending is True


# -- provider submit(): image (synchronous) ----------------------------------


def test_submit_seedream_image_succeeds_synchronously(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_post(self, url, **kwargs):  # type: ignore[no-untyped-def]
        assert url == "/v1/responses"
        return _FakeResponse(json_body={"data": [{"url": "https://cdn.invalid/out.png"}]})

    def fake_get(self, url, **kwargs):  # type: ignore[no-untyped-def]
        assert url == "https://cdn.invalid/out.png"
        return _FakeResponse(content=b"\x89PNG\r\n\x1a\nfake-png-bytes")

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    monkeypatch.setattr(httpx.Client, "get", fake_get)
    provider = _provider(Operation.TEXT_TO_IMAGE.value, SEEDREAM_5_PRO_MODEL)
    result = provider.submit(_request(Operation.TEXT_TO_IMAGE.value))

    assert result.succeeded is True
    assert result.pending is False
    assert result.mime_type == "image/png"
    assert s3.get_object(result.object_key) == b"\x89PNG\r\n\x1a\nfake-png-bytes"


def test_submit_seedream_image_missing_result_is_a_provider_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_post(self, url, **kwargs):  # type: ignore[no-untyped-def]
        return _FakeResponse(json_body={})

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    provider = _provider(Operation.TEXT_TO_IMAGE.value, SEEDREAM_5_PRO_MODEL)
    result = provider.submit(_request(Operation.TEXT_TO_IMAGE.value))

    assert result.succeeded is False
    assert result.failure_code == "PROVIDER_INVALID_RESPONSE"


def test_cancel_is_always_unsupported() -> None:
    assert _provider(Operation.TEXT_TO_VIDEO.value, MINIMAX_H3_MODEL).cancel("task-1") is False


# -- provider submit(): audio (synchronous) ----------------------------------


def test_submit_gpt4o_mini_tts_stores_the_raw_response_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audio_bytes = b"\xff\xfbfake-mp3-payload"

    def fake_post(self, url, **kwargs):  # type: ignore[no-untyped-def]
        assert url == "/v1/audio/speech"
        assert kwargs["json"] == {
            "model": AUDIO_MODEL_GPT4O_MINI_TTS,
            "input": "一只在雨夜霓虹街道上奔跑的机械狐狸",
            "voice": "nova",
            "response_format": "mp3",
        }
        return _FakeResponse(content=audio_bytes)

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    provider = _provider(Operation.AUDIO_GENERATION.value, AUDIO_MODEL_GPT4O_MINI_TTS)
    result = provider.submit(_request(Operation.AUDIO_GENERATION.value, extra={"voice": "nova"}))

    assert result.succeeded is True
    assert result.mime_type == "audio/mpeg"
    assert s3.get_object(result.object_key) == audio_bytes


def test_submit_tts_pro_forwards_the_emotion_field(monkeypatch: pytest.MonkeyPatch) -> None:
    audio_bytes = b"tts-pro-mp3-bytes"

    def fake_post(self, url, **kwargs):  # type: ignore[no-untyped-def]
        assert url == "/v1/audio/speech"
        assert kwargs["json"] == {
            "model": AUDIO_MODEL_TTS_PRO,
            "input": "一只在雨夜霓虹街道上奔跑的机械狐狸",
            "voice": "京腔小爷",
            "response_format": "mp3",
            "emotion": "happy",
        }
        return _FakeResponse(content=audio_bytes)

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    provider = _provider(Operation.AUDIO_GENERATION.value, AUDIO_MODEL_TTS_PRO)
    result = provider.submit(
        _request(
            Operation.AUDIO_GENERATION.value,
            extra={"voice": "京腔小爷", "emotion": "happy"},
        )
    )

    assert result.succeeded is True
    assert s3.get_object(result.object_key) == audio_bytes


def test_submit_tts_pro_without_emotion_omits_the_field(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_post(self, url, **kwargs):  # type: ignore[no-untyped-def]
        assert "emotion" not in kwargs["json"]
        return _FakeResponse(content=b"bytes")

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    provider = _provider(Operation.AUDIO_GENERATION.value, AUDIO_MODEL_TTS_PRO)
    result = provider.submit(
        _request(Operation.AUDIO_GENERATION.value, extra={"voice": "柔美女友"})
    )

    assert result.succeeded is True


def test_submit_audio_falls_back_to_a_default_voice_when_the_caller_omits_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_post(self, url, **kwargs):  # type: ignore[no-untyped-def]
        assert kwargs["json"]["voice"] == "alloy"
        return _FakeResponse(content=b"bytes")

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    provider = _provider(Operation.AUDIO_GENERATION.value, AUDIO_MODEL_GPT4O_MINI_TTS)
    result = provider.submit(_request(Operation.AUDIO_GENERATION.value, extra={}))

    assert result.succeeded is True


# -- request builder / response parsing: music-3.0 ---------------------------


def test_build_music_body_omits_lyrics_by_default() -> None:
    body = _build_music_body(_request(Operation.MUSIC_GENERATION.value, prompt="轻快的夏日民谣"))
    assert body == {
        "model": MUSIC_MODEL_DMX,
        "input": "轻快的夏日民谣",
        "is_instrumental": False,
    }


def test_build_music_body_carries_lyrics_when_not_instrumental() -> None:
    body = _build_music_body(
        _request(
            Operation.MUSIC_GENERATION.value,
            prompt="轻快的夏日民谣",
            extra={"lyrics": "[Verse]\n夏天的风吹过海岸"},
        )
    )
    assert body["lyrics"] == "[Verse]\n夏天的风吹过海岸"


def test_build_music_body_instrumental_omits_lyrics_even_if_provided() -> None:
    body = _build_music_body(
        _request(
            Operation.MUSIC_GENERATION.value,
            extra={"is_instrumental": True, "lyrics": "should be dropped"},
        )
    )
    assert body["is_instrumental"] is True
    assert "lyrics" not in body


def test_probe_music_body_is_a_plain_instrumental_request() -> None:
    body = probe_music_body()
    assert body["model"] == MUSIC_MODEL_DMX
    assert body["is_instrumental"] is True


def test_extract_music_result_reads_output_text_and_extra_info_duration() -> None:
    url, duration_ms = extract_music_result(
        {
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "https://cdn.invalid/song.mp3"}],
                }
            ],
            "extra_info": {"music_duration": 32000},
        }
    )
    assert url == "https://cdn.invalid/song.mp3"
    assert duration_ms == 32000


def test_extract_music_result_falls_back_to_seedream_shape() -> None:
    url, duration_ms = extract_music_result({"data": [{"url": "https://cdn.invalid/song.mp3"}]})
    assert url == "https://cdn.invalid/song.mp3"
    assert duration_ms is None


def test_submit_music_downloads_and_stores_the_finished_clip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    music_bytes = b"fake-mp3-song-bytes"
    music_url = "https://cdn.invalid/song.mp3"

    def fake_post(self, url, **kwargs):  # type: ignore[no-untyped-def]
        assert url == "/v1/responses"
        assert kwargs["json"] == {
            "model": MUSIC_MODEL_DMX,
            "input": "一只在雨夜霓虹街道上奔跑的机械狐狸",
            "is_instrumental": True,
        }
        return _FakeResponse(
            json_body={
                "output": [
                    {"type": "message", "content": [{"type": "output_text", "text": music_url}]}
                ],
                "extra_info": {"music_duration": 45000},
            }
        )

    def fake_get(self, url, **kwargs):  # type: ignore[no-untyped-def]
        assert url == music_url
        return _FakeResponse(content=music_bytes)

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    monkeypatch.setattr(httpx.Client, "get", fake_get)
    provider = _provider(Operation.MUSIC_GENERATION.value, MUSIC_MODEL_DMX)
    result = provider.submit(
        _request(Operation.MUSIC_GENERATION.value, extra={"is_instrumental": True})
    )

    assert result.succeeded is True
    assert result.pending is False
    assert result.mime_type == "audio/mpeg"
    assert result.duration_ms == 45000
    assert s3.get_object(result.object_key) == music_bytes


def test_submit_music_missing_url_is_a_provider_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_post(self, url, **kwargs):  # type: ignore[no-untyped-def]
        return _FakeResponse(json_body={})

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    provider = _provider(Operation.MUSIC_GENERATION.value, MUSIC_MODEL_DMX)
    result = provider.submit(_request(Operation.MUSIC_GENERATION.value))

    assert result.succeeded is False
    assert result.failure_code == "PROVIDER_INVALID_RESPONSE"
