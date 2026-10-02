"""fal.ai queue media provider for MiniMax H3 Max (video), MiniMax Voice
Clone (audio_generation), and MiniMax Music 2.6 / ElevenLabs Sound Effects
V2 (music_generation).

Speaks `POST https://queue.fal.run/{fal app id}/{route}` +
`GET .../requests/{id}/status` + `GET .../requests/{id}/response` +
`PUT .../requests/{id}/cancel`. Auth is `Authorization: Key $FAL_KEY`,
not Bearer. This is a different HTTP shape from `protocol=minimax`
(AiHubMix `/ai/v1/videos`), `protocol=minimax_v2` (official Video V2),
and `protocol=dmxapi` (`POST /v1/responses`).

Four model families, each its own `ProviderCapability`/catalog entry:

- `minimax/h3-max` (`_VIDEO_MODELS`): dispatches to three fal apps by
  reference shape — text-to-video, image-to-video (first/last frame),
  reference-to-video (multimodal).
- `minimax/voice-clone` (`_AUDIO_MODELS`): one app, no reference-shape
  dispatch. `fal-ai/minimax/voice-clone`'s own contract is a "clone +
  preview" call, not a persistent voice registry we manage: one
  `audio_url` (the reference sample) plus one `text` (the line to speak)
  returns `{"custom_voice_id", "audio": {"url": ...}}` in a single round
  trip — we only ever use the `audio.url` half, `custom_voice_id`'s 7-day
  voice-retention feature is not exercised here. This still reads as one
  atomic call from our side, which is why the plan called it "single-call
  clone" even though fal's own naming implies a two-step registry.
- `minimax-music/v2.6` (`_MUSIC_MODELS`): `prompt` (style/genre) plus an
  optional `lyrics` field; `is_instrumental` omits it entirely. No explicit
  duration control — the model picks its own length, up to ~60s.
- `elevenlabs/sound-effects/v2` (`_SFX_MODELS`): `text` describing the
  effect plus an explicit `duration_seconds` (0.5-22s) — the one model in
  this module whose music/SFX call takes a billable duration knob.

All three audio families share one fal app path shape (no route segment,
unlike the video routes) and one queue submit/poll/cancel skeleton — see
`_audio_app_path`/`FalMediaProvider._audio_route_and_body`.

Queue submit/poll/cancel follow fal's documented REST paths and have
**not** been verified against a live fal credential — every parser below
tolerates a few plausible shapes. Fix the specific function (not the
whole module) if a real call disagrees.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.providers.aihubmix_media import media_client_base, media_request_path
from app.providers.base import (
    GenerationProvider,
    GenerationRequest,
    GenerationResult,
    ProviderReference,
    probe_audio_duration_ms,
)
from app.storage import s3

logger = logging.getLogger(__name__)

FAL_H3_MAX_MODEL = "minimax/h3-max"
FAL_VOICE_CLONE_MODEL = "minimax/voice-clone"
FAL_MUSIC_MODEL = "minimax-music/v2.6"
FAL_SFX_MODEL = "elevenlabs/sound-effects/v2"

ROUTE_TEXT_TO_VIDEO = "text-to-video"
ROUTE_IMAGE_TO_VIDEO = "image-to-video"
ROUTE_REFERENCE_TO_VIDEO = "reference-to-video"
VALID_ROUTES = frozenset({ROUTE_TEXT_TO_VIDEO, ROUTE_IMAGE_TO_VIDEO, ROUTE_REFERENCE_TO_VIDEO})

# None of the three audio families (voice-clone/music/SFX) have more than
# one fal app or any reference-shape routing — these "routes" only
# namespace `encode_task_id`/`decode_task_id` the same way a real video
# route does; none is ever appended to the app path itself (see
# `_audio_app_path`, which is just `/{canonical_model}`).
ROUTE_VOICE_CLONE = "voice-clone"
ROUTE_MUSIC = "music"
ROUTE_SFX = "sfx"
VALID_AUDIO_ROUTES = frozenset({ROUTE_VOICE_CLONE, ROUTE_MUSIC, ROUTE_SFX})
_VIDEO_MODELS = frozenset({FAL_H3_MAX_MODEL})
_MUSIC_MODELS = frozenset({FAL_MUSIC_MODEL})
_SFX_MODELS = frozenset({FAL_SFX_MODEL})
_AUDIO_MODELS = frozenset({FAL_VOICE_CLONE_MODEL}) | _MUSIC_MODELS | _SFX_MODELS

_PROMPT_EXPANSION_MODE = "balanced"
_T2V_FALLBACK_RATIO = "16:9"
_REFERENCE_URL_TTL_SECONDS = 900
MAX_REFERENCE_FILES = 12
_FRAME_ROLES = frozenset({"first_frame", "last_frame"})
_ROUTE_SUFFIXES = tuple(f"/{route}" for route in sorted(VALID_ROUTES))

_PENDING_STATUSES = frozenset({"IN_QUEUE", "IN_PROGRESS"})
_COMPLETED_STATUS = "COMPLETED"


@dataclass(frozen=True, slots=True)
class VideoModelProfile:
    """One fal H3 Max model's physical limits."""

    min_duration_seconds: int
    max_duration_seconds: int
    aspect_ratios: frozenset[str]
    resolutions: frozenset[str]
    default_resolution: str | None
    reference_modes: frozenset[str] = field(default_factory=frozenset)


VIDEO_MODEL_PROFILES: dict[str, VideoModelProfile] = {
    FAL_H3_MAX_MODEL: VideoModelProfile(
        min_duration_seconds=5,
        max_duration_seconds=15,
        aspect_ratios=frozenset({"21:9", "16:9", "4:3", "1:1", "3:4", "9:16", "adaptive"}),
        resolutions=frozenset({"480P", "768P"}),
        default_resolution="768P",
        reference_modes=frozenset({"input_references", "frame_images"}),
    ),
}


def music_style_for_model(model: str) -> frozenset[str] | None:
    """Which `extra.audio_style` value(s) `model` actually produces, for
    `app.agents.router._request_constraint_failure`'s `music_generation`
    hard filter — `None` for a non-music model (voice-clone or video).
    `minimax-music/v2.6` is BGM-only; `elevenlabs/sound-effects/v2` is
    SFX-only — see the module docstring for why these are two separate fal
    apps sharing one `music_generation` capability tag, kept apart by this
    filter rather than merged into one model that tries to do both."""
    canonical = canonical_model(model)
    if canonical in _MUSIC_MODELS:
        return frozenset({"music"})
    if canonical in _SFX_MODELS:
        return frozenset({"sfx"})
    return None


def canonical_model(model: str) -> str:
    """Strip a full fal app id down to the catalog model.

    An operator who saved `minimax/h3-max/text-to-video` as `endpoint.model`
    still resolves to the H3 Max profile rather than looking like an
    unknown model with no hard filter.
    """
    stripped = model.strip().strip("/")
    for suffix in _ROUTE_SUFFIXES:
        if stripped.endswith(suffix):
            return stripped[: -len(suffix)]
    return stripped


def video_model_profile(model: str) -> VideoModelProfile | None:
    """The profile for a fal H3 Max model, if known.

    `None` for anything not in the table — callers treat that as "no extra
    validation, no hard filter", never as "reject it".
    """
    return VIDEO_MODEL_PROFILES.get(canonical_model(model))


def encode_task_id(route: str, request_id: str) -> str:
    return f"{route}#{request_id}"


def decode_task_id(external_task_id: str) -> tuple[str, str]:
    route, separator, request_id = external_task_id.partition("#")
    if not separator or route not in (VALID_ROUTES | VALID_AUDIO_ROUTES) or not request_id:
        raise ValueError(f"invalid fal task id: {external_task_id}")
    return route, request_id


def app_path(model: str, route: str) -> str:
    return f"/{canonical_model(model)}/{route}"


def _audio_app_path(model: str) -> str:
    """`minimax/voice-clone` has no sub-route segment — the fal app id is
    the entire path, unlike `app_path`'s video `{model}/{route}` shape."""
    return f"/{canonical_model(model)}"


def probe_submit_path(model: str) -> str:
    return app_path(model, ROUTE_TEXT_TO_VIDEO)


def _status_path(model: str, route: str, request_id: str) -> str:
    return f"{app_path(model, route)}/requests/{request_id}/status"


def _result_path(model: str, route: str, request_id: str) -> str:
    return f"{app_path(model, route)}/requests/{request_id}/response"


def _cancel_path(model: str, route: str, request_id: str) -> str:
    return f"{app_path(model, route)}/requests/{request_id}/cancel"


def probe_cancel_path(model: str, request_id: str) -> str:
    return _cancel_path(model, ROUTE_TEXT_TO_VIDEO, request_id)


def _audio_status_path(model: str, request_id: str) -> str:
    return f"{_audio_app_path(model)}/requests/{request_id}/status"


def _audio_result_path(model: str, request_id: str) -> str:
    return f"{_audio_app_path(model)}/requests/{request_id}/response"


def _audio_cancel_path(model: str, request_id: str) -> str:
    return f"{_audio_app_path(model)}/requests/{request_id}/cancel"


def _resolved_references(request: GenerationRequest) -> list[ProviderReference]:
    refs = list(request.references)
    if not refs and request.reference_object_keys:
        refs = [
            ProviderReference(object_key=key, media_type="image")
            for key in request.reference_object_keys
        ]
    return [ref for ref in refs if ref.frame_type != "base_video"]


def _presign(ref: ProviderReference) -> str:
    return s3.presign_get(ref.object_key, expires_in=_REFERENCE_URL_TTL_SECONDS)


def resolve_route(request: GenerationRequest) -> str:
    """Pick the fal app from the request's reference shape."""
    refs = _resolved_references(request)
    if not refs:
        return ROUTE_TEXT_TO_VIDEO

    frame_refs = [ref for ref in refs if ref.frame_type in _FRAME_ROLES]
    generic_refs = [ref for ref in refs if ref.frame_type not in _FRAME_ROLES]
    if frame_refs and generic_refs:
        raise ValueError("frame_images and input_references are mutually exclusive")

    if frame_refs:
        if any(ref.media_type != "image" for ref in frame_refs):
            raise ValueError("first/last frame references must be images")
        return ROUTE_IMAGE_TO_VIDEO

    if len(generic_refs) > MAX_REFERENCE_FILES:
        raise ValueError(
            f"{FAL_H3_MAX_MODEL} accepts at most {MAX_REFERENCE_FILES} reference files"
        )
    has_visual = any(ref.media_type in {"image", "video"} for ref in generic_refs)
    has_audio = any(ref.media_type == "audio" for ref in generic_refs)
    if has_audio and not has_visual:
        raise ValueError("audio cannot be the only reference")
    return ROUTE_REFERENCE_TO_VIDEO


def _validate_generation_request(
    model: str, request: GenerationRequest
) -> VideoModelProfile | None:
    profile = video_model_profile(model)
    if profile is None:
        return None
    if not profile.min_duration_seconds <= request.duration_seconds <= profile.max_duration_seconds:
        raise ValueError(
            f"{canonical_model(model)} duration must be between {profile.min_duration_seconds} and "
            f"{profile.max_duration_seconds} seconds"
        )
    if request.aspect_ratio not in profile.aspect_ratios:
        raise ValueError(
            f"{canonical_model(model)} aspect ratio is unsupported: {request.aspect_ratio}"
        )
    if request.resolution is not None and request.resolution not in profile.resolutions:
        raise ValueError(
            f"{canonical_model(model)} resolution is unsupported: {request.resolution}"
        )
    return profile


def _common_body(request: GenerationRequest, profile: VideoModelProfile | None) -> dict[str, Any]:
    prompt = request.prompt.strip()
    if not prompt:
        raise ValueError(f"{FAL_H3_MAX_MODEL} requires a non-empty text prompt")
    body: dict[str, Any] = {
        "prompt": prompt,
        "duration": request.duration_seconds,
        "prompt_expansion_mode": _PROMPT_EXPANSION_MODE,
        "enable_safety_checker": True,
    }
    resolution = request.resolution or (profile.default_resolution if profile else None)
    if resolution:
        body["resolution"] = resolution
    if request.seed is not None:
        body["seed"] = request.seed
    return body


def build_generation_body(
    request: GenerationRequest, *, model: str = FAL_H3_MAX_MODEL
) -> dict[str, Any]:
    """fal H3 Max create body for the route `resolve_route` selected.

    Text-to-video: no media fields; studio `adaptive` remaps to 16:9.
    Image-to-video: `image_url` / `end_image_url`; omit `aspect_ratio` when
    a first frame is present so fal follows the image.
    Reference-to-video: `reference_*_urls`; `adaptive` is allowed.
    """
    profile = _validate_generation_request(model, request)
    route = resolve_route(request)
    body = _common_body(request, profile)
    refs = _resolved_references(request)

    if route == ROUTE_TEXT_TO_VIDEO:
        ratio = _T2V_FALLBACK_RATIO if request.aspect_ratio == "adaptive" else request.aspect_ratio
        body["aspect_ratio"] = ratio
        return body

    if route == ROUTE_IMAGE_TO_VIDEO:
        first = next((ref for ref in refs if ref.frame_type == "first_frame"), None)
        last = next((ref for ref in refs if ref.frame_type == "last_frame"), None)
        if first is not None:
            body["image_url"] = _presign(first)
        else:
            body["aspect_ratio"] = (
                _T2V_FALLBACK_RATIO if request.aspect_ratio == "adaptive" else request.aspect_ratio
            )
        if last is not None:
            body["end_image_url"] = _presign(last)
        return body

    images = [_presign(ref) for ref in refs if ref.media_type == "image"]
    videos = [_presign(ref) for ref in refs if ref.media_type == "video"]
    audios = [_presign(ref) for ref in refs if ref.media_type == "audio"]
    if images:
        body["reference_image_urls"] = images
    if videos:
        body["reference_video_urls"] = videos
    if audios:
        body["reference_audio_urls"] = audios
    body["aspect_ratio"] = request.aspect_ratio
    return body


def probe_video_body(model: str = FAL_H3_MAX_MODEL) -> dict[str, Any]:
    """Minimal t2v body for admin connectivity — 480P / 5s / 16:9."""
    del model
    return {
        "prompt": "A static blue square, connectivity test.",
        "duration": 5,
        "resolution": "480P",
        "prompt_expansion_mode": _PROMPT_EXPANSION_MODE,
        "enable_safety_checker": True,
        "aspect_ratio": "16:9",
    }


def build_voice_clone_body(request: GenerationRequest) -> dict[str, Any]:
    """`fal-ai/minimax/voice-clone`'s body: exactly one reference audio
    (`audio_url`) plus the line to speak (`text`) — see the module
    docstring for why this one call already covers "clone and speak",
    without this codebase ever touching the returned `custom_voice_id`.

    `api.schemas.jobs.validate_generation_params` already caps
    `AUDIO_GENERATION`'s `reference_asset_ids` at exactly one entry and
    requires it to be `MediaType.AUDIO` (`media.service.
    validate_generation_references`), so a request that reaches this
    provider has already had both checked — this only re-derives the one
    reference from `request.references`, the same generic resolution path
    `provider_references_for` gives every other operation.
    """
    refs = [ref for ref in _resolved_references(request) if ref.media_type == "audio"]
    if not refs:
        raise ValueError(f"{FAL_VOICE_CLONE_MODEL} requires one voice-clone reference audio")
    body: dict[str, Any] = {"audio_url": _presign(refs[0])}
    text = request.prompt.strip()
    if text:
        body["text"] = text
    # `extra.voice` doubles as the optional preview-model hint here (fal's
    # own field is named `model`, not `voice` — there is no named voice
    # roster to pick from once a clone reference is attached, only which
    # MiniMax speech model renders the preview).
    preview_model = request.extra.get("voice")
    if isinstance(preview_model, str) and preview_model.strip():
        body["model"] = preview_model.strip()
    return body


_SFX_MIN_DURATION_SECONDS = 1
_SFX_MAX_DURATION_SECONDS = 22


def build_music_body(request: GenerationRequest) -> dict[str, Any]:
    """`fal-ai/minimax-music/v2.6` body: `prompt` is the style/genre
    description, `lyrics` is optional song lyrics (MiniMax's own
    `[Verse]`/`[Chorus]` structure tags belong in that text, not a separate
    field). `is_instrumental` omits `lyrics` entirely rather than sending an
    empty string — matching MiniMax's own "no lyrics field at all" means
    instrumental — the same convention `dmxapi_media.py::_build_music_body`
    follows for `music-3.0`. No duration control: the model decides its own
    length (confirmed against the model's fal.ai docs page, 2026-09; not
    yet exercised against a live credential).
    """
    prompt = request.prompt.strip()
    if not prompt:
        raise ValueError(f"{FAL_MUSIC_MODEL} requires a non-empty text prompt")
    body: dict[str, Any] = {"prompt": prompt}
    is_instrumental = bool(request.extra.get("is_instrumental"))
    lyrics = request.extra.get("lyrics")
    if not is_instrumental and isinstance(lyrics, str) and lyrics.strip():
        body["lyrics"] = lyrics.strip()
    return body


def build_sfx_body(request: GenerationRequest) -> dict[str, Any]:
    """`fal-ai/elevenlabs/sound-effects/v2` body: `text` describes the
    effect; `duration_seconds` (0.5-22s per ElevenLabs' own docs, clamped
    here to whole seconds) is the one music/SFX model in this module that
    takes an explicit, billable duration — a request that leaves
    `duration_seconds` at 0 (the `GenerationParams` default) lets the model
    pick its own length instead of forcing one. Confirmed against the
    model's fal.ai docs page (2026-09); not yet exercised against a live
    credential.
    """
    text = request.prompt.strip()
    if not text:
        raise ValueError(f"{FAL_SFX_MODEL} requires a non-empty text prompt")
    body: dict[str, Any] = {"text": text}
    if request.duration_seconds > 0:
        body["duration_seconds"] = min(
            max(request.duration_seconds, _SFX_MIN_DURATION_SECONDS), _SFX_MAX_DURATION_SECONDS
        )
    return body


def probe_audio_body(model: str = FAL_VOICE_CLONE_MODEL) -> dict[str, Any]:
    """Minimal connectivity body for whichever of the three audio families
    `model` names — fal's own published sample reference clip for voice
    clone, a short plain prompt for music/SFX."""
    canonical = canonical_model(model)
    if canonical in _MUSIC_MODELS:
        return {"prompt": "A short cheerful ukulele melody, connectivity test."}
    if canonical in _SFX_MODELS:
        return {"text": "A door creaking open, connectivity test.", "duration_seconds": 2}
    return {
        "audio_url": (
            "https://storage.googleapis.com/falserverless/model_tests/zonos/demo_voice_zonos.wav"
        ),
    }


def probe_audio_path(model: str) -> str:
    """The fal app path a `music_generation`/`audio_generation` connectivity
    probe posts to — same path `submit()` itself uses for that model. Used
    only by `app.providers.connectivity`, which has no `FalMediaProvider`
    instance of its own."""
    return _audio_app_path(model)


def probe_audio_cancel_path(model: str, request_id: str) -> str:
    return _audio_cancel_path(model, request_id)


def extract_request_id(payload: dict[str, Any]) -> str | None:
    """Create response: fal returns `{request_id}`; also accept `requestId`
    or a nested `request.id`. **Unverified against a live fal credential.**
    """
    request_id = payload.get("request_id") or payload.get("requestId")
    if request_id:
        return str(request_id)
    request = payload.get("request")
    if isinstance(request, dict) and request.get("id"):
        return str(request["id"])
    return None


def _error_message(payload: dict[str, Any]) -> str | None:
    error = payload.get("error")
    if isinstance(error, str) and error:
        return error
    if isinstance(error, dict):
        message = error.get("message") or error.get("detail") or error.get("type")
        return str(message) if message else None
    error_type = payload.get("error_type")
    return str(error_type) if error_type else None


def _video_url_from_result(payload: dict[str, Any]) -> str | None:
    video = payload.get("video")
    if isinstance(video, str) and video:
        return video
    if isinstance(video, dict):
        url = video.get("url")
        if isinstance(url, str) and url:
            return url
    return None


def _audio_url_from_result(payload: dict[str, Any]) -> str | None:
    audio = payload.get("audio")
    if isinstance(audio, str) and audio:
        return audio
    if isinstance(audio, dict):
        url = audio.get("url")
        if isinstance(url, str) and url:
            return url
    return None


def _http_error_detail(exc: httpx.HTTPStatusError, api_key: str) -> str:
    status = exc.response.status_code
    text = (exc.response.text or "").replace(api_key, "[redacted]")[:300]
    return f"HTTP {status}: {text}" if text else f"HTTP {status}"


@dataclass(frozen=True, slots=True)
class _EndpointCredentials:
    base_url: str
    api_key: str
    timeout_s: float


class FalMediaProvider(GenerationProvider):
    """One video or audio (voice-clone / music / SFX) capability of one
    `protocol="fal"` media endpoint — `self._model` decides which family;
    see the module docstring for the four."""

    kind = "commercial_api"

    def __init__(
        self,
        *,
        endpoint_id: str,
        capability_tag: str,
        model: str,
        base_url: str,
        api_key: str,
        timeout_ms: int,
    ) -> None:
        self.name = f"{endpoint_id}:{capability_tag}"
        self._capability_tag = capability_tag
        self._model = canonical_model(model)
        self._creds = _EndpointCredentials(
            base_url=base_url.rstrip("/"), api_key=api_key, timeout_s=timeout_ms / 1000
        )

    def _audio_route_and_body(self, request: GenerationRequest) -> tuple[str, dict[str, Any]]:
        """Which of the three audio families `self._model` is, and its
        create body — the one dispatch point every audio-shaped `submit()`
        call goes through."""
        if self._model == FAL_VOICE_CLONE_MODEL:
            return ROUTE_VOICE_CLONE, build_voice_clone_body(request)
        if self._model in _MUSIC_MODELS:
            return ROUTE_MUSIC, build_music_body(request)
        return ROUTE_SFX, build_sfx_body(request)

    def submit(self, request: GenerationRequest) -> GenerationResult:
        started = time.perf_counter()
        is_audio = self._model in _AUDIO_MODELS
        try:
            if is_audio:
                route, body = self._audio_route_and_body(request)
                path = _audio_app_path(self._model)
            else:
                route = resolve_route(request)
                body = build_generation_body(request, model=self._model)
                path = app_path(self._model, route)
            with self._client() as client:
                response = client.post(
                    media_request_path(self._creds.base_url, path),
                    json=body,
                )
                response.raise_for_status()
                payload = response.json()
        except ValueError as exc:
            return self._failure(started, "PROVIDER_INVALID_RESPONSE", str(exc))
        except httpx.TimeoutException as exc:
            logger.warning(
                "fal %s call timed out for job %s after %.0fs: %s",
                self._capability_tag,
                request.job_id,
                self._creds.timeout_s,
                type(exc).__name__,
            )
            return self._failure(
                started,
                "PROVIDER_TEMPORARY_FAILURE",
                f"{type(exc).__name__} after {int(self._creds.timeout_s)}s",
            )
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "fal %s call failed for job %s: HTTP %s",
                self._capability_tag,
                request.job_id,
                exc.response.status_code,
            )
            status = exc.response.status_code
            code = "PROVIDER_INVALID_RESPONSE" if status < 500 else "PROVIDER_TEMPORARY_FAILURE"
            return self._failure(started, code, _http_error_detail(exc, self._creds.api_key))
        except httpx.HTTPError as exc:
            logger.warning(
                "fal %s call failed for job %s: %s",
                self._capability_tag,
                request.job_id,
                exc,
            )
            return self._failure(started, "PROVIDER_TEMPORARY_FAILURE", type(exc).__name__)

        if not isinstance(payload, dict):
            return self._failure(started, "PROVIDER_INVALID_RESPONSE", "missing_request_id")
        request_id = extract_request_id(payload)
        if not request_id:
            return self._failure(started, "PROVIDER_INVALID_RESPONSE", "missing_request_id")

        return GenerationResult(
            succeeded=False,
            pending=True,
            mime_type="audio/mpeg" if is_audio else "video/mp4",
            # An audio call's real duration (clone/music/SFX alike) is only
            # known once the clip is downloaded in `poll()`
            # (`probe_audio_duration_ms`) — unlike video, where the
            # requested `duration_seconds` is itself the generated length.
            duration_ms=None if is_audio else request.duration_seconds * 1000,
            latency_ms=self._elapsed_ms(started),
            external_task_id=encode_task_id(route, request_id),
            metadata={"provider": self.name, "model": self._model, "route": route},
        )

    def poll(self, external_task_id: str, request: GenerationRequest) -> GenerationResult:
        """One query of fal queue status, then the result URL when COMPLETED.

        **Queue paths inferred from fal docs, not live-confirmed.** A
        transient HTTP error stays pending so the next Beat tick retries.
        """
        started = time.perf_counter()
        try:
            route, request_id = decode_task_id(external_task_id)
        except ValueError as exc:
            return self._failure(started, "PROVIDER_INVALID_RESPONSE", str(exc))
        is_audio = route in VALID_AUDIO_ROUTES

        try:
            with self._client() as client:
                status_path = (
                    _audio_status_path(self._model, request_id)
                    if is_audio
                    else _status_path(self._model, route, request_id)
                )
                response = client.get(media_request_path(self._creds.base_url, status_path))
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPError as exc:
            logger.warning("fal poll failed for task %s: %s", external_task_id, exc)
            return GenerationResult(
                succeeded=False,
                pending=True,
                external_task_id=external_task_id,
                latency_ms=self._elapsed_ms(started),
                metadata={"provider": self.name, "detail": type(exc).__name__},
            )

        if not isinstance(payload, dict):
            return self._failure(started, "PROVIDER_INVALID_RESPONSE", "invalid_poll_payload")
        status = str(payload.get("status") or "").upper()
        error_message = _error_message(payload)
        if status != _COMPLETED_STATUS:
            if status not in _PENDING_STATUSES:
                logger.info(
                    "fal poll saw unexpected status %s for task %s",
                    status,
                    external_task_id,
                )
            return GenerationResult(
                succeeded=False,
                pending=True,
                external_task_id=external_task_id,
                latency_ms=self._elapsed_ms(started),
                metadata={"provider": self.name, "status": status},
            )
        if error_message:
            return self._failure(started, "PROVIDER_TASK_FAILED", error_message)

        try:
            with self._client() as client:
                result_path = (
                    _audio_result_path(self._model, request_id)
                    if is_audio
                    else _result_path(self._model, route, request_id)
                )
                result_response = client.get(media_request_path(self._creds.base_url, result_path))
                result_response.raise_for_status()
                result_payload = result_response.json()
        except httpx.HTTPError as exc:
            logger.warning("fal result fetch failed for task %s: %s", external_task_id, exc)
            return GenerationResult(
                succeeded=False,
                pending=True,
                external_task_id=external_task_id,
                latency_ms=self._elapsed_ms(started),
                metadata={"provider": self.name, "detail": type(exc).__name__},
            )

        if not isinstance(result_payload, dict):
            return self._failure(started, "PROVIDER_INVALID_RESPONSE", "invalid_result_payload")
        result_error = _error_message(result_payload)
        if result_error:
            return self._failure(started, "PROVIDER_TASK_FAILED", result_error)
        media_url = (
            _audio_url_from_result(result_payload)
            if is_audio
            else _video_url_from_result(result_payload)
        )
        if not media_url:
            missing_code = "missing_audio_url" if is_audio else "missing_video_url"
            return self._failure(started, "PROVIDER_INVALID_RESPONSE", missing_code)

        try:
            with httpx.Client(timeout=self._creds.timeout_s) as download_client:
                download = download_client.get(media_url)
                download.raise_for_status()
                media_bytes = download.content or None
        except httpx.HTTPError as exc:
            logger.warning("fal media download failed for task %s: %s", external_task_id, exc)
            return GenerationResult(
                succeeded=False,
                pending=True,
                external_task_id=external_task_id,
                latency_ms=self._elapsed_ms(started),
                metadata={"provider": self.name, "detail": type(exc).__name__},
            )

        if not media_bytes:
            code = "empty_audio_content" if is_audio else "empty_video_content"
            return self._failure(started, "PROVIDER_INVALID_RESPONSE", code)

        if is_audio:
            object_key = f"generated/{request.job_id}/output_{request.attempt_number}.mp3"
            s3.put_object(object_key, media_bytes, content_type="audio/mpeg")
            return GenerationResult(
                succeeded=True,
                object_key=object_key,
                mime_type="audio/mpeg",
                duration_ms=probe_audio_duration_ms(media_bytes, "audio/mpeg"),
                latency_ms=self._elapsed_ms(started),
                external_task_id=external_task_id,
                metadata={
                    "provider": self.name,
                    "model": self._model,
                    "route": route,
                    "upstream_status": status,
                    "custom_voice_id": result_payload.get("custom_voice_id") or "",
                },
            )

        object_key = f"generated/{request.job_id}/output_{request.attempt_number}.mp4"
        s3.put_object(object_key, media_bytes, content_type="video/mp4")

        return GenerationResult(
            succeeded=True,
            object_key=object_key,
            mime_type="video/mp4",
            duration_ms=request.duration_seconds * 1000,
            latency_ms=self._elapsed_ms(started),
            external_task_id=external_task_id,
            metadata={
                "provider": self.name,
                "model": self._model,
                "route": route,
                "upstream_status": status,
            },
        )

    def cancel(self, external_task_id: str) -> bool:
        """`PUT .../requests/{id}/cancel`. 202 is success; 400 already-
        completed and 404 do not block the local CANCELLED transition.
        **Unverified against a live fal credential.**
        """
        try:
            route, request_id = decode_task_id(external_task_id)
        except ValueError:
            return False
        cancel_path = (
            _audio_cancel_path(self._model, request_id)
            if route in VALID_AUDIO_ROUTES
            else _cancel_path(self._model, route, request_id)
        )
        try:
            with self._client() as client:
                response = client.put(media_request_path(self._creds.base_url, cancel_path))
                return response.status_code < 400
        except httpx.HTTPError:
            return False

    def _client(self) -> httpx.Client:
        return httpx.Client(
            base_url=media_client_base(self._creds.base_url),
            headers={"Authorization": f"Key {self._creds.api_key}"},
            timeout=self._creds.timeout_s,
        )

    def _failure(self, started: float, code: str, detail: str) -> GenerationResult:
        return GenerationResult(
            succeeded=False,
            failure_code=code,
            latency_ms=self._elapsed_ms(started),
            metadata={"provider": self.name, "detail": detail},
        )

    @staticmethod
    def _elapsed_ms(started: float) -> int:
        return int((time.perf_counter() - started) * 1000)
