"""Single-endpoint connectivity checks never enter routing or persist outputs."""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

from app.models.enums import AudioGenerationKind, Operation
from app.platform_config.schemas import LlmProviderEndpoint
from app.providers import connectivity, dmxapi_media, fal_media


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


def test_media_openai_video_probe_hits_v1_videos_not_the_native_task_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An `openai`-protocol video endpoint speaks the OpenAI Videos API, not
    MiniMax's native `/ai/v1/videos` create shape — the probe must branch on
    `endpoint.protocol`, not assume every video endpoint is native."""
    calls: list[tuple[str, dict[str, object]]] = []

    def fake_post(self, path, **kwargs):  # type: ignore[no-untyped-def]
        calls.append((path, kwargs))
        request = httpx.Request("POST", f"https://media.invalid{path}")
        return httpx.Response(200, json={"id": "video_1"}, request=request)

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    result = connectivity.validate_endpoint(
        _media(
            model="wan2.7-videoedit",
            input_modalities=["text"],
            output_modalities=["video"],
            protocol="openai",
        )
    )

    assert result.reachable is True and result.usable is True
    assert [path for path, _ in calls] == ["/v1/videos"]
    body = calls[0][1]["json"]  # type: ignore[index]
    assert body["model"] == "wan2.7-videoedit"
    assert body["seconds"] == 5
    assert "resolution" not in body
    assert "aspect_ratio" not in body


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


def test_gpt_image_2_probe_sends_low_quality(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    def fake_post(self, path, **kwargs):  # type: ignore[no-untyped-def]
        calls.append((path, kwargs))
        request = httpx.Request("POST", f"https://media.invalid{path}")
        return httpx.Response(200, json={"data": [{"b64_json": "abc"}]}, request=request)

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    result = connectivity.validate_endpoint(
        _media(
            model="gpt-image-2",
            protocol="openai",
            input_modalities=["text", "image"],
            output_modalities=["image"],
        )
    )

    assert result.probe_type == Operation.TEXT_TO_IMAGE.value
    assert result.usable is True
    body = calls[0][1]["json"]
    assert body["model"] == "gpt-image-2"
    assert body["quality"] == "low"
    assert body["output_format"] == "png"
    assert body["size"] == "1024x1024"


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


def test_minimax_v2_video_probe_posts_to_v2_video_generation_and_reads_task_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Metaso / official MiniMax V2 is not the AiHubMix `/ai/v1/videos`
    facade — the probe must hit `/v2/video_generation` and take the task
    number from `task_id`, not from `id`."""
    calls: list[tuple[str, dict[str, object]]] = []

    def fake_post(self, path, **kwargs):  # type: ignore[no-untyped-def]
        calls.append((path, kwargs))
        request = httpx.Request("POST", f"https://metaso.cn{path}")
        return httpx.Response(200, json={"task_id": "424010985738629"}, request=request)

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    result = connectivity.validate_endpoint(
        _media(
            base_url="https://metaso.cn/api/minimax",
            model="MiniMax-H3",
            input_modalities=["text", "image", "video", "audio"],
            output_modalities=["video"],
            protocol="minimax_v2",
        )
    )

    assert result.reachable is True and result.usable is True
    assert [path for path, _ in calls] == ["/api/minimax/v2/video_generation"]
    body = calls[0][1]["json"]  # type: ignore[index]
    assert body["model"] == "MiniMax-H3"
    assert body["content"][0]["type"] == "text"
    assert body["resolution"] == "768P"
    assert body["duration"] == 4
    assert body["ratio"] == "16:9"
    assert result.external_task_id == "424010985738629"


def test_fal_video_probe_posts_to_h3_max_text_to_video_and_cancels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    posts: list[tuple[str, dict[str, object]]] = []
    puts: list[str] = []

    def fake_post(self, path, **kwargs):  # type: ignore[no-untyped-def]
        posts.append((path, kwargs))
        request = httpx.Request("POST", f"https://queue.fal.run{path}")
        return httpx.Response(
            200, json={"request_id": "764cabcf-b745-4b3e-ae38-1200304cf45b"}, request=request
        )

    def fake_put(self, path, **kwargs):  # type: ignore[no-untyped-def]
        puts.append(path)
        request = httpx.Request("PUT", f"https://queue.fal.run{path}")
        return httpx.Response(202, json={"status": "CANCELLATION_REQUESTED"}, request=request)

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    monkeypatch.setattr(httpx.Client, "put", fake_put)
    result = connectivity.validate_endpoint(
        _media(
            base_url="https://queue.fal.run",
            model="minimax/h3-max",
            input_modalities=["text", "image", "video", "audio"],
            output_modalities=["video"],
            protocol="fal",
        )
    )

    assert result.reachable is True and result.usable is True
    assert [path for path, _ in posts] == ["/minimax/h3-max/text-to-video"]
    body = posts[0][1]["json"]  # type: ignore[index]
    assert body["prompt_expansion_mode"] == "balanced"
    assert body["resolution"] == "480P"
    assert body["duration"] == 5
    assert result.external_task_id == "text-to-video#764cabcf-b745-4b3e-ae38-1200304cf45b"
    assert puts == [
        "/minimax/h3-max/text-to-video/requests/764cabcf-b745-4b3e-ae38-1200304cf45b/cancel"
    ]


def test_dmxapi_video_probe_posts_to_v1_responses_with_a_family_specific_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    def fake_post(self, path, **kwargs):  # type: ignore[no-untyped-def]
        calls.append((path, kwargs))
        request = httpx.Request("POST", f"https://www.dmxapi.cn{path}")
        return httpx.Response(200, json={"task_id": "task-1"}, request=request)

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    result = connectivity.validate_endpoint(
        _media(
            base_url="https://www.dmxapi.cn",
            model="MiniMax-H3",
            input_modalities=["text", "image", "video", "audio"],
            output_modalities=["video"],
            protocol="dmxapi",
        )
    )

    assert result.reachable is True and result.usable is True
    assert [path for path, _ in calls] == ["/v1/responses"]
    assert calls[0][1]["json"]["model"] == "MiniMax-H3"  # type: ignore[index]
    assert result.external_task_id == "task-1"


def test_dmxapi_video_regeneration_has_no_safe_probe_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """It always needs a real 768P source clip meeting an exact physical
    spec — there is no minimal request that could validate it safely, so
    the probe must not hit the network at all for this one model."""

    def fail_post(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("must not reach the network for this model")

    monkeypatch.setattr(httpx.Client, "post", fail_post)
    result = connectivity.validate_endpoint(
        _media(
            base_url="https://www.dmxapi.cn",
            model="MiniMax-H3-video_regeneration",
            input_modalities=["video"],
            output_modalities=["video"],
            protocol="dmxapi",
        )
    )

    assert result.reachable is False
    assert result.usable is False
    assert result.error_code == "no_capability"


def test_dmxapi_image_probe_posts_a_prompt_string_not_a_content_array(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    def fake_post(self, path, **kwargs):  # type: ignore[no-untyped-def]
        calls.append((path, kwargs))
        request = httpx.Request("POST", f"https://www.dmxapi.cn{path}")
        return httpx.Response(
            200, json={"data": [{"url": "https://cdn.invalid/out.png"}]}, request=request
        )

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    result = connectivity.validate_endpoint(
        _media(
            base_url="https://www.dmxapi.cn",
            model="doubao-seedream-5-0-pro-260628",
            input_modalities=["text", "image"],
            output_modalities=["image"],
            protocol="dmxapi",
        )
    )

    assert result.probe_type == Operation.TEXT_TO_IMAGE.value
    assert result.usable is True
    assert [path for path, _ in calls] == ["/v1/responses"]
    body = calls[0][1]["json"]  # type: ignore[index]
    assert isinstance(body["input"], str)
    assert "image" not in body


def test_dmxapi_audio_probe_posts_to_v1_audio_speech_and_checks_for_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    def fake_post(self, path, **kwargs):  # type: ignore[no-untyped-def]
        calls.append((path, kwargs))
        request = httpx.Request("POST", f"https://www.dmxapi.cn{path}")
        return httpx.Response(200, content=b"fake-mp3-bytes", request=request)

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    result = connectivity.validate_endpoint(
        _media(
            base_url="https://www.dmxapi.cn",
            model="tts-1",
            input_modalities=["text"],
            output_modalities=["audio"],
            protocol="dmxapi",
        )
    )

    assert result.probe_type == Operation.AUDIO_GENERATION.value
    assert result.reachable is True and result.usable is True
    assert [path for path, _ in calls] == ["/v1/audio/speech"]
    body = calls[0][1]["json"]  # type: ignore[index]
    assert body["model"] == "tts-1"
    assert body["voice"] == "alloy"
    assert body["response_format"] == "mp3"


def test_dmxapi_audio_probe_is_unusable_on_an_empty_body(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_post(self, path, **kwargs):  # type: ignore[no-untyped-def]
        request = httpx.Request("POST", f"https://www.dmxapi.cn{path}")
        return httpx.Response(200, content=b"", request=request)

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    result = connectivity.validate_endpoint(
        _media(
            base_url="https://www.dmxapi.cn",
            model="tts-1",
            input_modalities=["text"],
            output_modalities=["audio"],
            protocol="dmxapi",
        )
    )

    assert result.reachable is True
    assert result.usable is False
    assert result.error_code == "invalid_response"


def test_fal_audio_probe_posts_to_the_single_voice_clone_app_and_cancels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """fal's voice-clone route has no sub-route segment (unlike the video
    routes below) and — unlike the DMXAPI TTS probe above — is a queue
    submit, so this exercises `_probe_fal_audio`'s submit+best-effort-cancel
    skeleton rather than the synchronous audio-bytes path."""
    posts: list[tuple[str, dict[str, object]]] = []
    puts: list[str] = []

    def fake_post(self, path, **kwargs):  # type: ignore[no-untyped-def]
        posts.append((path, kwargs))
        request = httpx.Request("POST", f"https://queue.fal.run{path}")
        return httpx.Response(200, json={"request_id": "clone-req-1"}, request=request)

    def fake_put(self, path, **kwargs):  # type: ignore[no-untyped-def]
        puts.append(path)
        request = httpx.Request("PUT", f"https://queue.fal.run{path}")
        return httpx.Response(202, json={"status": "CANCELLATION_REQUESTED"}, request=request)

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    monkeypatch.setattr(httpx.Client, "put", fake_put)
    result = connectivity.validate_endpoint(
        _media(
            base_url="https://queue.fal.run",
            model=fal_media.FAL_VOICE_CLONE_MODEL,
            input_modalities=["text", "audio"],
            output_modalities=["audio"],
            protocol="fal",
        )
    )

    assert result.probe_type == Operation.AUDIO_GENERATION.value
    assert result.reachable is True and result.usable is True
    assert [path for path, _ in posts] == [f"/{fal_media.FAL_VOICE_CLONE_MODEL}"]
    body = posts[0][1]["json"]  # type: ignore[index]
    assert body["audio_url"].startswith("https://")
    assert result.external_task_id == "clone-req-1"
    assert puts == [f"/{fal_media.FAL_VOICE_CLONE_MODEL}/requests/clone-req-1/cancel"]


def test_dmxapi_music_probe_posts_an_instrumental_body_to_v1_responses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`audio_generation_kind="music"` is what makes an otherwise-identical
    `text -> audio` endpoint derive `MUSIC_GENERATION` instead of
    `AUDIO_GENERATION` — see `LlmProviderEndpoint.capabilities`."""
    calls: list[tuple[str, dict[str, object]]] = []

    def fake_post(self, path, **kwargs):  # type: ignore[no-untyped-def]
        calls.append((path, kwargs))
        request = httpx.Request("POST", f"https://www.dmxapi.cn{path}")
        return httpx.Response(
            200,
            json={"output": [{"content": [{"text": "https://cdn.invalid/clip.mp3"}]}]},
            request=request,
        )

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    result = connectivity.validate_endpoint(
        _media(
            base_url="https://www.dmxapi.cn",
            model=dmxapi_media.MUSIC_MODEL_DMX,
            input_modalities=["text"],
            output_modalities=["audio"],
            protocol="dmxapi",
            audio_generation_kind=AudioGenerationKind.MUSIC,
        )
    )

    assert result.probe_type == Operation.MUSIC_GENERATION.value
    assert result.reachable is True and result.usable is True
    assert [path for path, _ in calls] == ["/v1/responses"]
    body = calls[0][1]["json"]  # type: ignore[index]
    assert body["is_instrumental"] is True
    assert "lyrics" not in body


def test_dmxapi_music_probe_is_unusable_when_no_clip_url_comes_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_post(self, path, **kwargs):  # type: ignore[no-untyped-def]
        request = httpx.Request("POST", f"https://www.dmxapi.cn{path}")
        return httpx.Response(200, json={"output": []}, request=request)

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    result = connectivity.validate_endpoint(
        _media(
            base_url="https://www.dmxapi.cn",
            model=dmxapi_media.MUSIC_MODEL_DMX,
            input_modalities=["text"],
            output_modalities=["audio"],
            protocol="dmxapi",
            audio_generation_kind=AudioGenerationKind.MUSIC,
        )
    )

    assert result.reachable is True
    assert result.usable is False


def test_fal_music_probe_posts_to_the_music_app_and_cancels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    posts: list[tuple[str, dict[str, object]]] = []
    puts: list[str] = []

    def fake_post(self, path, **kwargs):  # type: ignore[no-untyped-def]
        posts.append((path, kwargs))
        request = httpx.Request("POST", f"https://queue.fal.run{path}")
        return httpx.Response(200, json={"request_id": "music-req-1"}, request=request)

    def fake_put(self, path, **kwargs):  # type: ignore[no-untyped-def]
        puts.append(path)
        request = httpx.Request("PUT", f"https://queue.fal.run{path}")
        return httpx.Response(202, json={"status": "CANCELLATION_REQUESTED"}, request=request)

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    monkeypatch.setattr(httpx.Client, "put", fake_put)
    result = connectivity.validate_endpoint(
        _media(
            base_url="https://queue.fal.run",
            model=fal_media.FAL_MUSIC_MODEL,
            input_modalities=["text"],
            output_modalities=["audio"],
            protocol="fal",
            audio_generation_kind=AudioGenerationKind.MUSIC,
        )
    )

    assert result.probe_type == Operation.MUSIC_GENERATION.value
    assert result.reachable is True and result.usable is True
    assert [path for path, _ in posts] == [f"/{fal_media.FAL_MUSIC_MODEL}"]
    body = posts[0][1]["json"]  # type: ignore[index]
    assert "prompt" in body
    assert result.external_task_id == "music-req-1"
    assert puts == [f"/{fal_media.FAL_MUSIC_MODEL}/requests/music-req-1/cancel"]


def test_fal_sfx_probe_posts_to_the_sfx_app_with_a_clamped_duration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same `MUSIC_GENERATION` capability, different fal app id — the SFX
    and BGM models share one connectivity code path (`_probe_fal_audio`),
    dispatching on `model` via `probe_audio_body`/`probe_audio_path`."""
    posts: list[tuple[str, dict[str, object]]] = []

    def fake_post(self, path, **kwargs):  # type: ignore[no-untyped-def]
        posts.append((path, kwargs))
        request = httpx.Request("POST", f"https://queue.fal.run{path}")
        return httpx.Response(200, json={"request_id": "sfx-req-1"}, request=request)

    def fake_put(self, path, **kwargs):  # type: ignore[no-untyped-def]
        request = httpx.Request("PUT", f"https://queue.fal.run{path}")
        return httpx.Response(202, json={}, request=request)

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    monkeypatch.setattr(httpx.Client, "put", fake_put)
    result = connectivity.validate_endpoint(
        _media(
            base_url="https://queue.fal.run",
            model=fal_media.FAL_SFX_MODEL,
            input_modalities=["text"],
            output_modalities=["audio"],
            protocol="fal",
            audio_generation_kind=AudioGenerationKind.MUSIC,
        )
    )

    assert result.probe_type == Operation.MUSIC_GENERATION.value
    assert result.reachable is True and result.usable is True
    assert [path for path, _ in posts] == [f"/{fal_media.FAL_SFX_MODEL}"]
    body = posts[0][1]["json"]  # type: ignore[index]
    assert body["text"]
    assert body["duration_seconds"] == 2
    assert result.external_task_id == "sfx-req-1"
