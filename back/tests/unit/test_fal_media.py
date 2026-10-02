"""fal.ai MiniMax H3 Max media provider."""

from __future__ import annotations

import httpx
import pytest

from app.models.enums import Operation
from app.providers.base import GenerationRequest, ProviderReference
from app.providers.fal_media import (
    FAL_H3_MAX_MODEL,
    FAL_MUSIC_MODEL,
    FAL_SFX_MODEL,
    FAL_VOICE_CLONE_MODEL,
    FalMediaProvider,
    build_generation_body,
    build_music_body,
    build_sfx_body,
    build_voice_clone_body,
    decode_task_id,
    encode_task_id,
    extract_request_id,
    probe_audio_body,
    probe_video_body,
    resolve_route,
    video_model_profile,
)
from app.storage import s3


def _provider() -> FalMediaProvider:
    return FalMediaProvider(
        endpoint_id="ep-fal",
        capability_tag=Operation.TEXT_TO_VIDEO.value,
        model=FAL_H3_MAX_MODEL,
        base_url="https://queue.fal.run",
        api_key="test-key",
        timeout_ms=5_000,
    )


def _voice_clone_provider() -> FalMediaProvider:
    return FalMediaProvider(
        endpoint_id="ep-fal-voice",
        capability_tag=Operation.AUDIO_GENERATION.value,
        model=FAL_VOICE_CLONE_MODEL,
        base_url="https://queue.fal.run",
        api_key="test-key",
        timeout_ms=5_000,
    )


def _music_provider() -> FalMediaProvider:
    return FalMediaProvider(
        endpoint_id="ep-fal-music",
        capability_tag=Operation.MUSIC_GENERATION.value,
        model=FAL_MUSIC_MODEL,
        base_url="https://queue.fal.run",
        api_key="test-key",
        timeout_ms=5_000,
    )


def _sfx_provider() -> FalMediaProvider:
    return FalMediaProvider(
        endpoint_id="ep-fal-sfx",
        capability_tag=Operation.MUSIC_GENERATION.value,
        model=FAL_SFX_MODEL,
        base_url="https://queue.fal.run",
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
            request = httpx.Request("GET", "https://queue.fal.run/minimax/h3-max/text-to-video")
            raise httpx.HTTPStatusError(
                "error",
                request=request,
                response=httpx.Response(self.status_code, request=request),
            )

    def json(self) -> dict:
        assert self._json_body is not None
        return self._json_body


def test_h3_max_profile_is_5_to_15_seconds_and_480p_768p() -> None:
    profile = video_model_profile(FAL_H3_MAX_MODEL)
    assert profile is not None
    assert profile.min_duration_seconds == 5
    assert profile.max_duration_seconds == 15
    assert profile.resolutions == frozenset({"480P", "768P"})
    assert profile.default_resolution == "768P"
    assert "adaptive" in profile.aspect_ratios
    assert "2K" not in profile.resolutions
    assert profile.reference_modes == frozenset({"input_references", "frame_images"})


def test_profile_lookup_strips_a_full_app_id() -> None:
    assert video_model_profile("minimax/h3-max/text-to-video") is not None
    assert video_model_profile("minimax/h3-max/reference-to-video") is video_model_profile(
        FAL_H3_MAX_MODEL
    )


def test_text_to_video_body_is_prompt_only() -> None:
    body = build_generation_body(_request(Operation.TEXT_TO_VIDEO.value))
    assert body["prompt"] == "一只在雨夜霓虹街道上奔跑的机械狐狸"
    assert body["duration"] == 5
    assert body["resolution"] == "768P"
    assert body["aspect_ratio"] == "16:9"
    assert body["prompt_expansion_mode"] == "balanced"
    assert body["enable_safety_checker"] is True
    assert "image_url" not in body
    assert "reference_image_urls" not in body
    assert resolve_route(_request(Operation.TEXT_TO_VIDEO.value)) == "text-to-video"


def test_text_to_video_remaps_adaptive_ratio_to_16_9() -> None:
    body = build_generation_body(_request(Operation.TEXT_TO_VIDEO.value, aspect_ratio="adaptive"))
    assert body["aspect_ratio"] == "16:9"


def test_rejects_an_out_of_range_duration() -> None:
    with pytest.raises(ValueError, match="duration must be between 5 and 15"):
        build_generation_body(_request(Operation.TEXT_TO_VIDEO.value, duration_seconds=4))
    with pytest.raises(ValueError, match="duration must be between 5 and 15"):
        build_generation_body(_request(Operation.TEXT_TO_VIDEO.value, duration_seconds=20))


def test_rejects_an_empty_prompt() -> None:
    with pytest.raises(ValueError, match="non-empty text prompt"):
        build_generation_body(_request(Operation.TEXT_TO_VIDEO.value, prompt="   "))


def test_first_last_frame_uses_image_to_video_and_omits_aspect_ratio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(s3, "presign_get", lambda key, **kwargs: f"https://signed.invalid/{key}")
    request = _request(
        Operation.IMAGE_TO_VIDEO.value,
        aspect_ratio="16:9",
        references=[
            ProviderReference(object_key="first.png", media_type="image", frame_type="first_frame"),
            ProviderReference(object_key="last.png", media_type="image", frame_type="last_frame"),
        ],
    )
    assert resolve_route(request) == "image-to-video"
    body = build_generation_body(request)
    assert body["image_url"] == "https://signed.invalid/first.png"
    assert body["end_image_url"] == "https://signed.invalid/last.png"
    assert "aspect_ratio" not in body
    assert body["prompt_expansion_mode"] == "balanced"


def test_generic_references_use_reference_to_video(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(s3, "presign_get", lambda key, **kwargs: f"https://signed.invalid/{key}")
    request = _request(
        Operation.VIDEO_TO_VIDEO.value,
        aspect_ratio="adaptive",
        references=[
            ProviderReference(object_key="hero.png", media_type="image"),
            ProviderReference(object_key="motion.mp4", media_type="video"),
            ProviderReference(object_key="line.mp3", media_type="audio"),
        ],
    )
    assert resolve_route(request) == "reference-to-video"
    body = build_generation_body(request)
    assert body["aspect_ratio"] == "adaptive"
    assert body["reference_image_urls"] == ["https://signed.invalid/hero.png"]
    assert body["reference_video_urls"] == ["https://signed.invalid/motion.mp4"]
    assert body["reference_audio_urls"] == ["https://signed.invalid/line.mp3"]


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


def test_audio_cannot_be_the_only_reference() -> None:
    with pytest.raises(ValueError, match="audio cannot be the only reference"):
        resolve_route(
            _request(
                Operation.VIDEO_TO_VIDEO.value,
                references=[ProviderReference(object_key="line.mp3", media_type="audio")],
            )
        )


def test_encode_and_decode_task_id() -> None:
    encoded = encode_task_id("text-to-video", "764cabcf-b745-4b3e-ae38-1200304cf45b")
    assert encoded == "text-to-video#764cabcf-b745-4b3e-ae38-1200304cf45b"
    assert decode_task_id(encoded) == (
        "text-to-video",
        "764cabcf-b745-4b3e-ae38-1200304cf45b",
    )
    with pytest.raises(ValueError, match="invalid fal task id"):
        decode_task_id("764cabcf-b745-4b3e-ae38-1200304cf45b")


def test_extract_request_id_tolerates_nested_and_flat_shapes() -> None:
    assert extract_request_id({"request_id": "req-1"}) == "req-1"
    assert extract_request_id({"requestId": "req-2"}) == "req-2"
    assert extract_request_id({"request": {"id": "nested-1"}}) == "nested-1"
    assert extract_request_id({}) is None


def test_probe_body_is_a_cheap_480p_text_to_video() -> None:
    body = probe_video_body()
    assert body["resolution"] == "480P"
    assert body["duration"] == 5
    assert body["aspect_ratio"] == "16:9"
    assert body["prompt_expansion_mode"] == "balanced"


def test_submit_returns_pending_with_encoded_task_id(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_post(self, url, **kwargs):  # type: ignore[no-untyped-def]
        captured["url"] = url
        captured["authorization"] = self.headers.get("Authorization")
        captured["json"] = kwargs["json"]
        return _FakeResponse(json_body={"request_id": "764cabcf-b745-4b3e-ae38-1200304cf45b"})

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    result = _provider().submit(_request(Operation.TEXT_TO_VIDEO.value))

    assert captured["url"] == "/minimax/h3-max/text-to-video"
    assert captured["authorization"] == "Key test-key"
    assert captured["json"]["prompt_expansion_mode"] == "balanced"
    assert result.pending is True
    assert result.external_task_id == "text-to-video#764cabcf-b745-4b3e-ae38-1200304cf45b"


def test_submit_image_to_video_hits_the_i2v_app(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(s3, "presign_get", lambda key, **kwargs: f"https://signed.invalid/{key}")
    captured: dict[str, object] = {}

    def fake_post(self, url, **kwargs):  # type: ignore[no-untyped-def]
        captured["url"] = url
        return _FakeResponse(json_body={"request_id": "i2v-1"})

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    result = _provider().submit(
        _request(
            Operation.IMAGE_TO_VIDEO.value,
            references=[
                ProviderReference(
                    object_key="first.png", media_type="image", frame_type="first_frame"
                )
            ],
        )
    )
    assert captured["url"] == "/minimax/h3-max/image-to-video"
    assert result.external_task_id == "image-to-video#i2v-1"


def test_submit_missing_request_id_is_a_provider_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_post(self, url, **kwargs):  # type: ignore[no-untyped-def]
        return _FakeResponse(json_body={"queue_position": 0})

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    result = _provider().submit(_request(Operation.TEXT_TO_VIDEO.value))
    assert result.succeeded is False
    assert result.failure_code == "PROVIDER_INVALID_RESPONSE"


def test_poll_downloads_the_finished_video(monkeypatch: pytest.MonkeyPatch) -> None:
    video_bytes = b"h3-max-mp4-bytes"
    video_url = "https://v3b.fal.media/files/example.mp4"
    task_id = "text-to-video#764cabcf-b745-4b3e-ae38-1200304cf45b"

    def fake_get(self, url, **kwargs):  # type: ignore[no-untyped-def]
        if url == video_url:
            return _FakeResponse(content=video_bytes)
        if url.endswith("/status"):
            return _FakeResponse(json_body={"status": "COMPLETED", "request_id": "764cabcf"})
        assert url == (
            "/minimax/h3-max/text-to-video/requests/764cabcf-b745-4b3e-ae38-1200304cf45b/response"
        )
        return _FakeResponse(json_body={"video": {"url": video_url, "content_type": "video/mp4"}})

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    result = _provider().poll(task_id, _request(Operation.TEXT_TO_VIDEO.value, duration_seconds=5))

    assert result.succeeded is True
    assert result.mime_type == "video/mp4"
    assert s3.get_object(result.object_key) == video_bytes


def test_poll_stays_pending_while_in_queue(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get(self, url, **kwargs):  # type: ignore[no-untyped-def]
        return _FakeResponse(json_body={"status": "IN_QUEUE", "queue_position": 2})

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    result = _provider().poll("text-to-video#task-1", _request(Operation.TEXT_TO_VIDEO.value))
    assert result.pending is True
    assert result.succeeded is False


def test_poll_http_error_stays_pending(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get(self, url, **kwargs):  # type: ignore[no-untyped-def]
        raise httpx.ConnectError("transient")

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    result = _provider().poll("text-to-video#task-1", _request(Operation.TEXT_TO_VIDEO.value))
    assert result.pending is True
    assert result.succeeded is False
    assert result.failure_code is None


def test_poll_completed_with_error_is_a_task_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get(self, url, **kwargs):  # type: ignore[no-untyped-def]
        return _FakeResponse(
            json_body={"status": "COMPLETED", "error": "sensitive content", "error_type": "content"}
        )

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    result = _provider().poll("text-to-video#task-1", _request(Operation.TEXT_TO_VIDEO.value))
    assert result.succeeded is False
    assert result.failure_code == "PROVIDER_TASK_FAILED"
    assert "sensitive" in str(result.metadata.get("detail"))


def test_cancel_puts_the_queue_cancel_path(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[str] = []

    def fake_put(self, url, **kwargs):  # type: ignore[no-untyped-def]
        captured.append(url)
        return _FakeResponse(json_body={"status": "CANCELLATION_REQUESTED"}, status_code=202)

    monkeypatch.setattr(httpx.Client, "put", fake_put)
    assert _provider().cancel("text-to-video#764cabcf-b745-4b3e-ae38-1200304cf45b") is True
    assert captured == [
        "/minimax/h3-max/text-to-video/requests/764cabcf-b745-4b3e-ae38-1200304cf45b/cancel"
    ]


def test_cancel_returns_false_on_already_completed(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_put(self, url, **kwargs):  # type: ignore[no-untyped-def]
        return _FakeResponse(json_body={"status": "ALREADY_COMPLETED"}, status_code=400)

    monkeypatch.setattr(httpx.Client, "put", fake_put)
    assert _provider().cancel("text-to-video#task-1") is False


def test_cancel_returns_false_on_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_put(self, url, **kwargs):  # type: ignore[no-untyped-def]
        raise httpx.ConnectError("boom")

    monkeypatch.setattr(httpx.Client, "put", fake_put)
    assert _provider().cancel("text-to-video#task-1") is False


def _audio_request(**overrides: object) -> GenerationRequest:
    defaults: dict[str, object] = {
        "job_id": "job-voice-clone",
        "operation": Operation.AUDIO_GENERATION.value,
        "quality_tier": "standard",
        "prompt": "你好，这是一段克隆声音的试听文本。",
        "references": [ProviderReference(object_key="sample.mp3", media_type="audio")],
    }
    defaults.update(overrides)
    return GenerationRequest(**defaults)  # type: ignore[arg-type]


def test_voice_clone_body_uses_the_one_reference_audio_and_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(s3, "presign_get", lambda key, **kwargs: f"https://signed.invalid/{key}")
    body = build_voice_clone_body(_audio_request())
    assert body["audio_url"] == "https://signed.invalid/sample.mp3"
    assert body["text"] == "你好，这是一段克隆声音的试听文本。"
    assert "model" not in body


def test_voice_clone_body_passes_through_an_extra_voice_as_the_preview_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(s3, "presign_get", lambda key, **kwargs: f"https://signed.invalid/{key}")
    body = build_voice_clone_body(_audio_request(extra={"voice": "speech-2.6-hd"}))
    assert body["model"] == "speech-2.6-hd"


def test_voice_clone_body_requires_an_audio_reference() -> None:
    with pytest.raises(ValueError, match="requires one voice-clone reference audio"):
        build_voice_clone_body(_audio_request(references=[]))


def test_probe_audio_body_is_fals_own_sample_clip() -> None:
    body = probe_audio_body()
    assert body["audio_url"].startswith("https://storage.googleapis.com/")


def test_voice_clone_submit_posts_to_the_single_voice_clone_app(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(s3, "presign_get", lambda key, **kwargs: f"https://signed.invalid/{key}")
    captured: dict[str, object] = {}

    def fake_post(self, url, **kwargs):  # type: ignore[no-untyped-def]
        captured["url"] = url
        captured["json"] = kwargs["json"]
        return _FakeResponse(json_body={"request_id": "clone-req-1"})

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    result = _voice_clone_provider().submit(_audio_request())

    assert captured["url"] == "/minimax/voice-clone"
    assert captured["json"]["audio_url"] == "https://signed.invalid/sample.mp3"
    assert result.pending is True
    assert result.mime_type == "audio/mpeg"
    assert result.duration_ms is None
    assert result.external_task_id == "voice-clone#clone-req-1"


def test_voice_clone_poll_downloads_the_cloned_audio(monkeypatch: pytest.MonkeyPatch) -> None:
    audio_bytes = b"cloned-voice-mp3-bytes"
    audio_url = "https://v3b.fal.media/files/example.mp3"
    task_id = "voice-clone#clone-req-1"

    def fake_get(self, url, **kwargs):  # type: ignore[no-untyped-def]
        if url == audio_url:
            return _FakeResponse(content=audio_bytes)
        if url.endswith("/status"):
            return _FakeResponse(json_body={"status": "COMPLETED", "request_id": "clone-req-1"})
        assert url == "/minimax/voice-clone/requests/clone-req-1/response"
        return _FakeResponse(
            json_body={
                "custom_voice_id": "voice-abc",
                "audio": {"url": audio_url, "content_type": "audio/mpeg"},
            }
        )

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    result = _voice_clone_provider().poll(task_id, _audio_request())

    assert result.succeeded is True
    assert result.mime_type == "audio/mpeg"
    assert result.metadata["custom_voice_id"] == "voice-abc"
    assert s3.get_object(result.object_key) == audio_bytes


def test_voice_clone_poll_stays_pending_while_in_queue(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get(self, url, **kwargs):  # type: ignore[no-untyped-def]
        return _FakeResponse(json_body={"status": "IN_QUEUE", "queue_position": 3})

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    result = _voice_clone_provider().poll("voice-clone#task-1", _audio_request())
    assert result.pending is True
    assert result.succeeded is False


def test_voice_clone_cancel_puts_the_voice_clone_cancel_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[str] = []

    def fake_put(self, url, **kwargs):  # type: ignore[no-untyped-def]
        captured.append(url)
        return _FakeResponse(json_body={"status": "CANCELLATION_REQUESTED"}, status_code=202)

    monkeypatch.setattr(httpx.Client, "put", fake_put)
    assert _voice_clone_provider().cancel("voice-clone#clone-req-1") is True
    assert captured == ["/minimax/voice-clone/requests/clone-req-1/cancel"]


# -- music_generation: minimax-music/v2.6 and elevenlabs/sound-effects/v2 ----


def _music_request(**overrides: object) -> GenerationRequest:
    defaults: dict[str, object] = {
        "job_id": "job-music",
        "operation": Operation.MUSIC_GENERATION.value,
        "quality_tier": "standard",
        "prompt": "轻快的夏日民谣，尤克里里伴奏",
    }
    defaults.update(overrides)
    return GenerationRequest(**defaults)  # type: ignore[arg-type]


def test_build_music_body_omits_lyrics_by_default() -> None:
    body = build_music_body(_music_request())
    assert body == {"prompt": "轻快的夏日民谣，尤克里里伴奏"}


def test_build_music_body_carries_lyrics_when_not_instrumental() -> None:
    body = build_music_body(_music_request(extra={"lyrics": "[Verse]\n夏天的风吹过海岸"}))
    assert body["lyrics"] == "[Verse]\n夏天的风吹过海岸"


def test_build_music_body_instrumental_omits_lyrics_even_if_provided() -> None:
    body = build_music_body(
        _music_request(extra={"is_instrumental": True, "lyrics": "should be dropped"})
    )
    assert "lyrics" not in body


def test_build_music_body_requires_a_non_empty_prompt() -> None:
    with pytest.raises(ValueError, match="non-empty text prompt"):
        build_music_body(_music_request(prompt="   "))


def test_build_sfx_body_includes_a_clamped_duration() -> None:
    body = build_sfx_body(_music_request(prompt="门缓缓打开的声音", duration_seconds=5))
    assert body == {"text": "门缓缓打开的声音", "duration_seconds": 5}


def test_build_sfx_body_omits_duration_when_unset() -> None:
    body = build_sfx_body(_music_request(prompt="门缓缓打开的声音"))
    assert body == {"text": "门缓缓打开的声音"}


def test_build_sfx_body_clamps_duration_to_the_1_to_22_second_window() -> None:
    body = build_sfx_body(_music_request(prompt="爆炸声", duration_seconds=100))
    assert body["duration_seconds"] == 22


def test_build_sfx_body_requires_a_non_empty_prompt() -> None:
    with pytest.raises(ValueError, match="non-empty text prompt"):
        build_sfx_body(_music_request(prompt=""))


def test_probe_audio_body_dispatches_by_model_family() -> None:
    assert "prompt" in probe_audio_body(FAL_MUSIC_MODEL)
    sfx_probe = probe_audio_body(FAL_SFX_MODEL)
    assert sfx_probe["text"]
    assert sfx_probe["duration_seconds"] == 2
    assert probe_audio_body(FAL_VOICE_CLONE_MODEL)["audio_url"].startswith(
        "https://storage.googleapis.com/"
    )


def test_music_submit_posts_to_the_music_app_with_no_route_segment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_post(self, url, **kwargs):  # type: ignore[no-untyped-def]
        captured["url"] = url
        captured["json"] = kwargs["json"]
        return _FakeResponse(json_body={"request_id": "music-req-1"})

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    result = _music_provider().submit(_music_request())

    assert captured["url"] == "/minimax-music/v2.6"
    assert captured["json"] == {"prompt": "轻快的夏日民谣，尤克里里伴奏"}
    assert result.pending is True
    assert result.mime_type == "audio/mpeg"
    assert result.duration_ms is None
    assert result.external_task_id == "music#music-req-1"


def test_sfx_submit_posts_to_the_sfx_app(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_post(self, url, **kwargs):  # type: ignore[no-untyped-def]
        captured["url"] = url
        captured["json"] = kwargs["json"]
        return _FakeResponse(json_body={"request_id": "sfx-req-1"})

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    result = _sfx_provider().submit(_music_request(prompt="玻璃破碎声", duration_seconds=3))

    assert captured["url"] == "/elevenlabs/sound-effects/v2"
    assert captured["json"] == {"text": "玻璃破碎声", "duration_seconds": 3}
    assert result.pending is True
    assert result.external_task_id == "sfx#sfx-req-1"


def test_music_poll_downloads_the_finished_track(monkeypatch: pytest.MonkeyPatch) -> None:
    music_bytes = b"minimax-music-mp3-bytes"
    music_url = "https://v3b.fal.media/files/song.mp3"
    task_id = "music#music-req-1"

    def fake_get(self, url, **kwargs):  # type: ignore[no-untyped-def]
        if url == music_url:
            return _FakeResponse(content=music_bytes)
        if url.endswith("/status"):
            return _FakeResponse(json_body={"status": "COMPLETED", "request_id": "music-req-1"})
        assert url == "/minimax-music/v2.6/requests/music-req-1/response"
        return _FakeResponse(json_body={"audio": {"url": music_url, "content_type": "audio/mpeg"}})

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    result = _music_provider().poll(task_id, _music_request())

    assert result.succeeded is True
    assert result.mime_type == "audio/mpeg"
    assert s3.get_object(result.object_key) == music_bytes


def test_sfx_poll_downloads_the_finished_clip(monkeypatch: pytest.MonkeyPatch) -> None:
    sfx_bytes = b"elevenlabs-sfx-mp3-bytes"
    sfx_url = "https://v3b.fal.media/files/glass.mp3"
    task_id = "sfx#sfx-req-1"

    def fake_get(self, url, **kwargs):  # type: ignore[no-untyped-def]
        if url == sfx_url:
            return _FakeResponse(content=sfx_bytes)
        if url.endswith("/status"):
            return _FakeResponse(json_body={"status": "COMPLETED", "request_id": "sfx-req-1"})
        assert url == "/elevenlabs/sound-effects/v2/requests/sfx-req-1/response"
        return _FakeResponse(json_body={"audio": {"url": sfx_url, "content_type": "audio/mpeg"}})

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    result = _sfx_provider().poll(task_id, _music_request(prompt="玻璃破碎声", duration_seconds=3))

    assert result.succeeded is True
    assert s3.get_object(result.object_key) == sfx_bytes


def test_music_poll_stays_pending_while_in_queue(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get(self, url, **kwargs):  # type: ignore[no-untyped-def]
        return _FakeResponse(json_body={"status": "IN_QUEUE", "queue_position": 1})

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    result = _music_provider().poll("music#task-1", _music_request())
    assert result.pending is True
    assert result.succeeded is False


def test_music_cancel_puts_the_music_cancel_path(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[str] = []

    def fake_put(self, url, **kwargs):  # type: ignore[no-untyped-def]
        captured.append(url)
        return _FakeResponse(json_body={"status": "CANCELLATION_REQUESTED"}, status_code=202)

    monkeypatch.setattr(httpx.Client, "put", fake_put)
    assert _music_provider().cancel("music#music-req-1") is True
    assert captured == ["/minimax-music/v2.6/requests/music-req-1/cancel"]
