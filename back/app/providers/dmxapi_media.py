"""DMXAPI media provider.

DMXAPI aggregates many upstream vendors (MiniMax, ByteDance Doubao, Alibaba
Wan/DashScope, ...) behind one unified HTTP contract for most of what it
sells: synchronous image generation (`doubao-seedream-5-0-pro-260628`) and
submit-task-then-poll video generation (`MiniMax-H3`, its video-regeneration
mode, `doubao-seedance-2-5-260628`, `wan3.0-video`) all go through a single
`POST /v1/responses` endpoint. That is DMXAPI's own repurposing of the
OpenAI "Responses API" shape as a generic task envelope, not the real
OpenAI Responses API; the request/response *body* shape is different for
every model family, so this provider dispatches internally by `model`, the
same way `AiHubMixMediaProvider` dispatches by `capability_tag`/`protocol`.
`audio_generation` (`_AUDIO_MODELS`) is the one capability that does *not*
share that envelope: it's a synchronous, OpenAI-shaped `POST /v1/audio/
speech` call instead, identical in contract (if not upstream account) to
`aihubmix_media.py`'s own `_submit_audio`.

`music_generation` (`_MUSIC_MODELS` — `music-3.0`) is a third shape: back on
the shared `/v1/responses` envelope (unlike `audio_generation`), but
synchronous like it — a completed clip comes back in the same call, no
task id to poll — with its own `input`/`lyrics`/`is_instrumental` body
instead of any video family's.

Sourced from DMXAPI's own published docs (`doc.dmxapi.cn`, checked 2026-08).
None of this has been exercised against a live credential yet — every
per-model response-parsing function below is written to tolerate a few
plausible shapes rather than betting on exactly one, and says so; fix the
relevant function (not the whole module) once a live call disagrees.
"""

from __future__ import annotations

import base64
import io
import logging
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
from PIL import Image, UnidentifiedImageError

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

# -- model identifiers -------------------------------------------------------
# Casing is exactly what DMXAPI's own docs send in the `model` field — never
# normalised, since the upstream gateway matches on the literal string (and
# differs from AiHubMix's own, separately-lowercased catalogue for what is
# otherwise "the same" model — the two providers never share a lookup table).
MINIMAX_H3_MODEL = "MiniMax-H3"
MINIMAX_H3_REGENERATION_MODEL = "MiniMax-H3-video_regeneration"
DOUBAO_SEEDANCE_25_MODEL = "doubao-seedance-2-5-260628"
WAN3_VIDEO_MODEL = "wan3.0-video"
SEEDREAM_5_PRO_MODEL = "doubao-seedream-5-0-pro-260628"

_VIDEO_MODELS = frozenset(
    {MINIMAX_H3_MODEL, MINIMAX_H3_REGENERATION_MODEL, DOUBAO_SEEDANCE_25_MODEL, WAN3_VIDEO_MODEL}
)
_IMAGE_MODELS = frozenset({SEEDREAM_5_PRO_MODEL})

# -- audio_generation models --------------------------------------------------
# All four hit the same `/v1/audio/speech` endpoint (`doc.dmxapi.cn/openai-
# tts.html` / `tts-pro.html`) — an OpenAI-shaped request/response, identical
# in *contract* to `aihubmix_media.py`'s own `_submit_audio`, just a
# different upstream account. `gpt-4o-mini-tts`/`tts-1`/`tts-1-hd` accept the
# OpenAI voice roster (`alloy`/`ash`/`ballad`/`coral`/`echo`/`fable`/`onyx`/
# `nova`/`sage`/`shimmer`/`verse`); `tts-pro` is a distinct upstream (ByteDance
# Volcano) resold through the identical endpoint shape, with its own several-
# dozen Chinese voice roster and an extra `emotion` field
# (`happy`/`angry`/`fear`/`surprise`) — neither roster is enumerated here,
# same reasoning as `api.schemas.jobs.AUDIO_VOICE_MAX_LENGTH` dropping the
# fixed set: the studio's per-model picker is the source of truth for which
# ids are legal, not this provider.
AUDIO_MODEL_GPT4O_MINI_TTS = "gpt-4o-mini-tts"
AUDIO_MODEL_TTS_1 = "tts-1"
AUDIO_MODEL_TTS_1_HD = "tts-1-hd"
AUDIO_MODEL_TTS_PRO = "tts-pro"
_OPENAI_TTS_MODELS = frozenset(
    {AUDIO_MODEL_GPT4O_MINI_TTS, AUDIO_MODEL_TTS_1, AUDIO_MODEL_TTS_1_HD}
)
_AUDIO_MODELS = _OPENAI_TTS_MODELS | {AUDIO_MODEL_TTS_PRO}
# `voice` is required on this endpoint; a request without one (e.g. a stale
# client) still gets *a* voice rather than a 4xx neither roster can recover
# from client-side. Not a recommendation — the studio always sends a real
# choice.
_DEFAULT_VOICE_BY_MODEL: dict[str, str] = {
    AUDIO_MODEL_GPT4O_MINI_TTS: "alloy",
    AUDIO_MODEL_TTS_1: "alloy",
    AUDIO_MODEL_TTS_1_HD: "alloy",
    AUDIO_MODEL_TTS_PRO: "柔美女友",
}

# -- music_generation models --------------------------------------------------
# MiniMax Music 3.0 resold through DMXAPI's own `/v1/responses` envelope
# (`doc.dmxapi.cn/music-3.0-text-to-music.html`), but — unlike every video
# family on that same endpoint — synchronous: the finished clip's URL comes
# back in the create response itself, no `task_id` to poll. Music-only, no
# separate sound-effects mode; SFX goes through fal's ElevenLabs model
# instead (`fal_media.py::FAL_SFX_MODEL`).
MUSIC_MODEL_DMX = "music-3.0"
_MUSIC_MODELS = frozenset({MUSIC_MODEL_DMX})


def music_style_for_model(model: str) -> frozenset[str] | None:
    """Which `extra.audio_style` value(s) `model` actually produces, for
    `app.agents.router._request_constraint_failure`'s `music_generation`
    hard filter — `None` for a non-music model. `music-3.0` is BGM-only;
    DMXAPI has no separate SFX endpoint, so this side of `music_generation`
    never returns `{"sfx"}` (see `app.providers.fal_media.
    music_style_for_model` for the fal SFX half)."""
    return frozenset({"music"}) if model in _MUSIC_MODELS else None


# The polling `model` id each video family answers to — DMXAPI's own
# `"{family}-get"` convention, confirmed on doc.dmxapi.cn's text-to-video page
# for three of the four. `MiniMax-H3-video_regeneration`'s own poll model id
# was not confirmed on a page this research could fully retrieve; reusing the
# plain generation family's poll model is the strongest available guess
# (regeneration is "just another H3 task" per MiniMax's own upstream API) —
# verify against a live credential before trusting it.
_POLL_MODEL_BY_VIDEO_MODEL: dict[str, str] = {
    MINIMAX_H3_MODEL: "MiniMax-H3-get",
    MINIMAX_H3_REGENERATION_MODEL: "MiniMax-H3-get",
    DOUBAO_SEEDANCE_25_MODEL: "seedance-2-5-get",
    WAN3_VIDEO_MODEL: "wan3.0-get",
}

# Anything else (`succeeded`/`pending`/`running`/`queued`/`in_progress`/...)
# reads as "still working" — an allow-list would strand an unrecognised
# in-progress status in limbo forever, the same reasoning AiHubMix's own
# OpenAI-videos-track poll uses.
_TERMINAL_FAILURE_STATUSES = frozenset({"failed", "cancelled", "canceled"})
_TERMINAL_STATUSES = _TERMINAL_FAILURE_STATUSES | {"succeeded"}

_REFERENCE_URL_TTL_SECONDS = 900
_SEEDREAM_MAX_REFERENCES = 10


@dataclass(frozen=True, slots=True)
class VideoModelProfile:
    """One DMXAPI video model's physical limits, sourced from doc.dmxapi.cn."""

    min_duration_seconds: int
    max_duration_seconds: int
    aspect_ratios: frozenset[str]
    resolutions: frozenset[str]
    default_resolution: str | None
    supports_auto_duration: bool = False
    # What kinds of reference this model accepts, for the catalogue's
    # `reference_modes` hint — not itself enforced here (see
    # `media_endpoints.py::dynamic_capabilities`).
    reference_modes: frozenset[str] = field(default_factory=frozenset)
    # `MiniMax-H3-video_regeneration` only: the source clip's own physical
    # spec is validated by the upstream, not here (see
    # `_build_minimax_h3_regeneration_body`'s docstring) — this model has no
    # duration/aspect-ratio/resolution of its own to pick.
    requires_video_reference: bool = False


VIDEO_MODEL_PROFILES: dict[str, VideoModelProfile] = {
    MINIMAX_H3_MODEL: VideoModelProfile(
        min_duration_seconds=4,
        max_duration_seconds=15,
        aspect_ratios=frozenset({"21:9", "16:9", "4:3", "1:1", "3:4", "9:16"}),
        resolutions=frozenset({"768P", "2K"}),
        default_resolution="2K",
        reference_modes=frozenset({"input_references", "frame_images"}),
    ),
    MINIMAX_H3_REGENERATION_MODEL: VideoModelProfile(
        min_duration_seconds=4,
        max_duration_seconds=15,
        aspect_ratios=frozenset(),
        resolutions=frozenset({"2K"}),
        default_resolution="2K",
        requires_video_reference=True,
    ),
    DOUBAO_SEEDANCE_25_MODEL: VideoModelProfile(
        min_duration_seconds=4,
        max_duration_seconds=30,
        aspect_ratios=frozenset({"16:9", "4:3", "1:1", "3:4", "9:16", "21:9", "adaptive"}),
        resolutions=frozenset({"480p", "720p", "1080p"}),
        default_resolution="720p",
        supports_auto_duration=True,
        reference_modes=frozenset({"input_references", "frame_images"}),
    ),
    WAN3_VIDEO_MODEL: VideoModelProfile(
        min_duration_seconds=2,
        max_duration_seconds=30,
        aspect_ratios=frozenset({"adaptive", "16:9", "4:3", "1:1", "3:4", "9:16"}),
        resolutions=frozenset({"480P", "720P", "1080P"}),
        default_resolution="1080P",
        supports_auto_duration=True,
        reference_modes=frozenset({"input_references", "frame_images"}),
    ),
}


def video_model_profile(model: str) -> VideoModelProfile | None:
    """The profile for a DMXAPI video model's contract, if known.

    `None` for anything not in the table above — callers must treat that as
    "no additional validation, no hard filter", never as "reject it".
    """
    return VIDEO_MODEL_PROFILES.get(model.strip())


@dataclass(frozen=True, slots=True)
class ImageModelProfile:
    """One DMXAPI image model's physical limits."""

    max_reference_count: int
    size_tiers: frozenset[str]
    min_total_pixels: int
    max_total_pixels: int
    min_aspect_ratio: float
    max_aspect_ratio: float


IMAGE_MODEL_PROFILES: dict[str, ImageModelProfile] = {
    SEEDREAM_5_PRO_MODEL: ImageModelProfile(
        max_reference_count=10,
        size_tiers=frozenset({"1K", "2K"}),
        min_total_pixels=921_600,
        max_total_pixels=4_194_304,
        min_aspect_ratio=1 / 16,
        max_aspect_ratio=16.0,
    ),
}


def image_model_profile(model: str) -> ImageModelProfile | None:
    """The profile for a DMXAPI image model's contract, if known."""
    return IMAGE_MODEL_PROFILES.get(model.strip())


# Exact pixel sizes for common aspect ratios at each quality tier, from the
# vendor's own aspect-ratio table for Doubao Seedream 5.0 Pro — cross-checked
# via two independent DMXAPI-compatible aggregators' docs (apimart.ai,
# evolink.ai), since DMXAPI's own page only demonstrated the ambiguous
# `"size": "1K"` bare-tier form without a full ratio table. Every entry's
# total pixel count sits inside this model's documented
# `[921600, 4194304]` window.
_SEEDREAM_SIZE_BY_ASPECT: dict[str, dict[str, str]] = {
    "1:1": {"1K": "1024x1024", "2K": "2048x2048"},
    "16:9": {"1K": "1424x800", "2K": "2816x1584"},
    "9:16": {"1K": "800x1424", "2K": "1584x2816"},
    "4:3": {"1K": "1152x864", "2K": "2368x1776"},
    "3:4": {"1K": "864x1152", "2K": "1776x2368"},
    "3:2": {"1K": "1248x832", "2K": "2496x1664"},
    "2:3": {"1K": "832x1248", "2K": "1664x2496"},
    "21:9": {"1K": "1568x672", "2K": "3136x1344"},
}


def _seedream_size_for(aspect_ratio: str, quality_tier: str) -> str:
    """An exact `WxH` when the aspect ratio is a known one, else the bare
    tier string — DMXAPI honours both, falling back to letting the model
    infer geometry from the prompt for an aspect this table does not cover."""
    tier = "2K" if quality_tier == "cinematic" else "1K"
    return _SEEDREAM_SIZE_BY_ASPECT.get(aspect_ratio, {}).get(tier, tier)


def _validate_video_request(model: str, request: GenerationRequest) -> VideoModelProfile | None:
    """Same shape as `aihubmix_media.build_video_payload`'s inline checks,
    kept here instead of shared: DMXAPI's profile fields
    (`reference_modes`/`requires_video_reference`) don't exist on AiHubMix's
    `NativeVideoModelProfile`, so a shared validator would need to grow a
    union type for one caller."""
    profile = video_model_profile(model)
    if profile is None or profile.requires_video_reference:
        return profile
    is_auto_duration = request.duration_seconds == -1 and profile.supports_auto_duration
    if not is_auto_duration and not (
        profile.min_duration_seconds <= request.duration_seconds <= profile.max_duration_seconds
    ):
        raise ValueError(
            f"{model} duration must be between {profile.min_duration_seconds} and "
            f"{profile.max_duration_seconds} seconds"
        )
    if profile.aspect_ratios and request.aspect_ratio not in profile.aspect_ratios:
        raise ValueError(f"{model} aspect ratio is unsupported: {request.aspect_ratio}")
    if request.resolution is not None and request.resolution not in profile.resolutions:
        raise ValueError(f"{model} resolution is unsupported: {request.resolution}")
    return profile


# -- video request builders --------------------------------------------------

_FRAME_ROLES = frozenset({"first_frame", "last_frame"})
_DEFAULT_REFERENCE_ROLE = {
    "image": "reference_image",
    "video": "reference_video",
    "audio": "reference_audio",
}


def _resolved_references(request: GenerationRequest) -> list[ProviderReference]:
    refs = list(request.references)
    if not refs and request.reference_object_keys:
        refs = [
            ProviderReference(object_key=key, media_type="image")
            for key in request.reference_object_keys
        ]
    return refs


def _content_items_from_references(request: GenerationRequest) -> list[dict[str, Any]]:
    """MiniMax's own multi-modal `content`/`input` array shape: one item per
    reference, `type` from the media kind and `role` from `ProviderReference
    .frame_type` when it names a positional frame, else a generic reference
    role derived from `media_type` (see `ProviderReference` docstring in
    `app/providers/base.py` for why `frame_type` covers both cases now)."""
    items: list[dict[str, Any]] = []
    for ref in _resolved_references(request):
        if ref.frame_type == "base_video":
            continue  # handled separately by the regeneration builder
        url = s3.presign_get(ref.object_key, expires_in=_REFERENCE_URL_TTL_SECONDS)
        item_type = f"{ref.media_type}_url"
        role = (
            ref.frame_type
            if ref.frame_type in _FRAME_ROLES
            else _DEFAULT_REFERENCE_ROLE.get(ref.media_type, "reference_image")
        )
        items.append({"type": item_type, item_type: {"url": url}, "role": role})
    return items


def _build_minimax_h3_body(request: GenerationRequest) -> dict[str, Any]:
    profile = _validate_video_request(MINIMAX_H3_MODEL, request)
    content = _content_items_from_references(request)
    content.insert(0, {"type": "text", "text": request.prompt})
    body: dict[str, Any] = {
        "model": MINIMAX_H3_MODEL,
        "input": content,
        "duration": request.duration_seconds,
        "ratio": request.aspect_ratio,
    }
    resolution = request.resolution or (profile.default_resolution if profile else None)
    if resolution:
        body["resolution"] = resolution
    return body


def _build_minimax_h3_regeneration_body(request: GenerationRequest) -> dict[str, Any]:
    """MiniMax-H3 video regeneration: re-submits the *original* 768P
    generation's exact input, plus exactly one `role=base_video` item, to
    get a 2K remaster back.

    The platform does not persist a past job's original multi-modal
    `content` array today, so this builder can only faithfully reconstruct
    the two fields the product surface actually carries forward into a new
    `video_to_video` request: the original text prompt (`request.prompt`)
    and the source clip itself (the one reference tagged
    `frame_type="base_video"`). Any other input the *original* 768P
    generation used (reference images/videos/voice) is not reproduced —
    regeneration will fail upstream if the source clip was produced from
    anything beyond a plain prompt. This is a known, documented limitation
    (see the plan's "已知限制" section), not a bug to silently work around
    here; teaching the platform to persist/replay a job's full original
    input is a separate, larger change.
    """
    base_video = next((ref for ref in request.references if ref.frame_type == "base_video"), None)
    if base_video is None:
        raise ValueError(
            f"{MINIMAX_H3_REGENERATION_MODEL} requires a reference tagged frame_type=base_video"
        )
    url = s3.presign_get(base_video.object_key, expires_in=_REFERENCE_URL_TTL_SECONDS)
    return {
        "model": MINIMAX_H3_REGENERATION_MODEL,
        "input": [
            {"type": "text", "text": request.prompt},
            {"type": "video_url", "video_url": {"url": url}, "role": "base_video"},
        ],
    }


def _build_seedance_25_video_body(request: GenerationRequest) -> dict[str, Any]:
    """DMXAPI `/v1/responses` body for `doubao-seedance-2-5-260628`.

    Official docs put every modality into `input` — text plus
    `image_url` / `video_url` / `audio_url` items with a `role`
    (`first_frame` / `last_frame` / `reference_image` /
    `reference_video` / `reference_audio`). There is no top-level
    `input_references` or `frame_images`; sending either is a live 400
    (`unsupported parameter: input_references`). First-frame and
    first/last-frame tasks only accept `ratio=adaptive`. First/last
    frame and multimodal `reference_*` roles are mutually exclusive.
    """
    profile = _validate_video_request(DOUBAO_SEEDANCE_25_MODEL, request)
    media_items = _content_items_from_references(request)
    roles = {item.get("role") for item in media_items}
    frame_roles = roles & _FRAME_ROLES
    reference_roles = roles - _FRAME_ROLES - {None}
    if frame_roles and reference_roles:
        raise ValueError("frame_images and input_references are mutually exclusive")
    body: dict[str, Any] = {
        "model": DOUBAO_SEEDANCE_25_MODEL,
        "input": [{"type": "text", "text": request.prompt}, *media_items],
        "duration": request.duration_seconds,
        "ratio": "adaptive" if frame_roles else request.aspect_ratio,
    }
    resolution = request.resolution or (profile.default_resolution if profile else None)
    if resolution:
        body["resolution"] = resolution
    generate_audio = request.extra.get("generate_audio")
    if generate_audio is not None:
        body["generate_audio"] = generate_audio
    return body


def _wan3_media_items(request: GenerationRequest) -> list[dict[str, Any]]:
    """Wan3.0's own media-role vocabulary: `first_frame`/`last_frame` for
    image-to-video, `reference_image`/`reference_video`/`reference_audio`
    for multi-modal reference generation, and `reference_video` alone (with
    an edit-intent prompt, e.g. "转换成...风格"/"移除...") for video-to-video
    editing — the caller signals which by what it puts in `request.prompt`,
    same as the vendor's own contract (there is no separate "edit" flag)."""
    items: list[dict[str, Any]] = []
    for ref in _resolved_references(request):
        role = (
            ref.frame_type
            if ref.frame_type in _FRAME_ROLES
            else _DEFAULT_REFERENCE_ROLE.get(ref.media_type, "reference_image")
        )
        items.append(
            {
                "type": role,
                "url": s3.presign_get(ref.object_key, expires_in=_REFERENCE_URL_TTL_SECONDS),
            }
        )
    return items


def _build_wan3_body(request: GenerationRequest) -> dict[str, Any]:
    profile = _validate_video_request(WAN3_VIDEO_MODEL, request)
    media = _wan3_media_items(request)
    input_body: dict[str, Any] = {}
    if request.prompt.strip():
        input_body["prompt"] = request.prompt
    if media:
        input_body["media"] = media
    if not input_body:
        raise ValueError(f"{WAN3_VIDEO_MODEL} requires a prompt or at least one media reference")
    parameters: dict[str, Any] = {
        "duration": request.duration_seconds,
        "ratio": request.aspect_ratio,
        # DMXAPI's documented default; kept explicit rather than omitted so
        # a short prompt still benefits from the vendor's own rewrite pass.
        "prompt_extend": True,
    }
    resolution = request.resolution or (profile.default_resolution if profile else None)
    if resolution:
        parameters["resolution"] = resolution
    if request.seed is not None:
        parameters["seed"] = request.seed
    generate_audio = request.extra.get("generate_audio")
    if generate_audio is not None:
        parameters["audio"] = generate_audio
    return {"model": WAN3_VIDEO_MODEL, "input": input_body, "parameters": parameters}


def probe_video_body(model: str) -> dict[str, Any]:
    """A minimal, valid request body for `/v1/responses` connectivity
    testing — enough to satisfy each family's required fields without a
    real `GenerationRequest`. Used only by `app.providers.connectivity`.

    `MiniMax-H3-video_regeneration` has no connectivity-safe minimal body —
    it always needs a real 768P source clip that meets an exact physical
    spec — so this raises for that one model; the caller must not offer a
    probe button for it.
    """
    if model == MINIMAX_H3_MODEL:
        return {
            "model": model,
            "input": [{"type": "text", "text": "A static blue square, connectivity test."}],
            "duration": 4,
            "resolution": "768P",
            "ratio": "16:9",
        }
    if model == DOUBAO_SEEDANCE_25_MODEL:
        return {
            "model": model,
            "input": [{"type": "text", "text": "A static blue square, connectivity test."}],
            "duration": 4,
            "resolution": "480p",
            "ratio": "16:9",
        }
    if model == WAN3_VIDEO_MODEL:
        return {
            "model": model,
            "input": {"prompt": "A static blue square, connectivity test."},
            "parameters": {"duration": 2, "resolution": "480P", "ratio": "16:9"},
        }
    raise ValueError(f"no connectivity probe body for dmxapi model: {model}")


def _build_video_body(model: str, request: GenerationRequest) -> dict[str, Any]:
    if model == MINIMAX_H3_MODEL:
        return _build_minimax_h3_body(request)
    if model == MINIMAX_H3_REGENERATION_MODEL:
        return _build_minimax_h3_regeneration_body(request)
    if model == DOUBAO_SEEDANCE_25_MODEL:
        return _build_seedance_25_video_body(request)
    if model == WAN3_VIDEO_MODEL:
        return _build_wan3_body(request)
    raise ValueError(f"unknown dmxapi video model: {model}")


# -- music request builder ----------------------------------------------------


def _build_music_body(request: GenerationRequest) -> dict[str, Any]:
    """DMXAPI `/v1/responses` body for `music-3.0` — its own `input`/
    `lyrics`/`is_instrumental` shape, not any video family's `input`-array
    envelope. `is_instrumental` omits `lyrics` entirely rather than sending
    an empty string, matching MiniMax's own upstream "no lyrics field at
    all" instrumental convention; a lyrics-carrying call is expected to
    write structure tags (`[Verse]`/`[Chorus]`) straight into the text, same
    as fal's `minimax-music` builder (`fal_media.py::build_music_body`).
    """
    body: dict[str, Any] = {
        "model": MUSIC_MODEL_DMX,
        "input": request.prompt,
    }
    is_instrumental = bool(request.extra.get("is_instrumental"))
    body["is_instrumental"] = is_instrumental
    lyrics = request.extra.get("lyrics")
    if not is_instrumental and isinstance(lyrics, str) and lyrics.strip():
        body["lyrics"] = lyrics.strip()
    return body


def probe_music_body() -> dict[str, Any]:
    """Minimal connectivity body for `music-3.0` — a plain instrumental
    request avoids any lyrics-shape ambiguity. Used only by
    `app.providers.connectivity`."""
    return {
        "model": MUSIC_MODEL_DMX,
        "input": "A short cheerful ukulele melody, connectivity test.",
        "is_instrumental": True,
    }


def extract_music_result(payload: dict[str, Any]) -> tuple[str | None, int | None]:
    """Returns `(audio_url, duration_ms)` from a `music-3.0` completed
    response — `None`s if the shape could not be parsed.

    Sourced from `doc.dmxapi.cn/music-3.0-text-to-music.html`'s sample: the
    finished clip's URL sits in the same `output[].content[].text` slot
    every other `/v1/responses` family uses for its "here is the result"
    payload (see `_first_output_text`), with the vendor's own
    `extra_info.music_duration` (already milliseconds per that page's
    sample) alongside it when present. Falls back to
    `extract_seedream_result`'s `data[]`/nested-`output[]` shapes for a
    response that instead wraps the URL image-style — same defensive
    tolerance as everywhere else in this not-yet-live-verified module.
    """
    url = _first_output_text(payload)
    if not (isinstance(url, str) and url.startswith("http")):
        url, _ = extract_seedream_result(payload)
    duration_ms: int | None = None
    extra_info = payload.get("extra_info")
    if isinstance(extra_info, dict):
        raw_duration = extra_info.get("music_duration")
        if isinstance(raw_duration, int | float) and raw_duration > 0:
            duration_ms = int(raw_duration)
    return url, duration_ms


# -- image request builder ---------------------------------------------------


def _image_reference_urls(request: GenerationRequest) -> list[str]:
    keys: list[str] = []
    for ref in request.references:
        if ref.media_type == "image" and ref.object_key:
            keys.append(ref.object_key)
    for key in request.reference_object_keys:
        if key not in keys:
            keys.append(key)
    keys = keys[:_SEEDREAM_MAX_REFERENCES]
    return [s3.presign_get(key, expires_in=_REFERENCE_URL_TTL_SECONDS) for key in keys]


def _build_seedream_body(request: GenerationRequest) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": SEEDREAM_5_PRO_MODEL,
        "input": request.prompt,
        "output_format": "png",
    }
    image_refs = _image_reference_urls(request)
    if image_refs:
        body["image"] = image_refs[0] if len(image_refs) == 1 else image_refs
    body["size"] = _seedream_size_for(request.aspect_ratio, request.quality_tier)
    return body


# -- response parsing ---------------------------------------------------------


def _first_output_text(payload: dict[str, Any]) -> str | None:
    """`output[0].content[0].text` — the one shape every family's Responses-
    style envelope has been confirmed to use for its "here is the id/url"
    payload (task id on create, the finished asset's URL on a completed
    poll)."""
    output = payload.get("output")
    if not isinstance(output, list) or not output:
        return None
    first = output[0]
    if not isinstance(first, dict):
        return None
    content = first.get("content")
    if not isinstance(content, list) or not content:
        return None
    part = content[0]
    if not isinstance(part, dict):
        return None
    text = part.get("text") or part.get("output_text")
    return text if isinstance(text, str) and text else None


def extract_task_id(model: str, payload: dict[str, Any]) -> str | None:
    """Every family's create response has been confirmed with its own task-id
    field name — `task_id` for the MiniMax-H3 family, `id` for Seedance,
    `provider_metadata.task_id` (with the id also echoed as the bare
    `output[].content[].text`) for wan3.0-video."""
    if model in (MINIMAX_H3_MODEL, MINIMAX_H3_REGENERATION_MODEL):
        task_id = payload.get("task_id")
        return str(task_id) if task_id else None
    if model == DOUBAO_SEEDANCE_25_MODEL:
        task_id = payload.get("id")
        return str(task_id) if task_id else None
    if model == WAN3_VIDEO_MODEL:
        metadata = payload.get("provider_metadata")
        if isinstance(metadata, dict):
            task_id = metadata.get("task_id")
            if task_id:
                return str(task_id)
        return _first_output_text(payload)
    return None


def _poll_result(model: str, payload: dict[str, Any]) -> tuple[str, str | None, str | None]:
    """Returns `(status, video_url_if_done, error_message_if_failed)`.

    `status` is normalised lowercase; a caller treats anything outside
    `_TERMINAL_STATUSES` as still pending. The MiniMax-H3 family nests its
    poll result under `task` (confirmed shape: `task.status` /
    `task.content.url` / `task.error`); Seedance answers with `status` and
    `output[].content[].text` directly at the top level (confirmed shape);
    wan3.0-video's completed-task sample this research retrieved had no
    top-level `status` field at all, only the final URL in `output[]` — so
    completion there is inferred from whether that text looks like a URL,
    with `provider_metadata.task_status` (if present) taking priority when
    it disagrees. **The wan3.0-video branch is the least certain of the
    three — verify against a live credential before trusting it.**
    """
    if model in (MINIMAX_H3_MODEL, MINIMAX_H3_REGENERATION_MODEL):
        task = payload.get("task")
        if not isinstance(task, dict):
            return "unknown", None, None
        status = str(task.get("status") or "").lower()
        content = task.get("content")
        url = content.get("url") if isinstance(content, dict) else None
        error = task.get("error")
        message = (
            error
            if isinstance(error, str)
            else (error.get("message") if isinstance(error, dict) else None)
        )
        return status, (url if isinstance(url, str) and url else None), message
    if model == DOUBAO_SEEDANCE_25_MODEL:
        status = str(payload.get("status") or "").lower()
        url = _first_output_text(payload)
        error_message = (
            str(payload.get("error") or status) if status in _TERMINAL_FAILURE_STATUSES else None
        )
        return status, (url if status == "succeeded" else None), error_message
    if model == WAN3_VIDEO_MODEL:
        metadata = payload.get("provider_metadata")
        raw_status = metadata.get("task_status") if isinstance(metadata, dict) else None
        text = _first_output_text(payload)
        looks_like_url = isinstance(text, str) and text.startswith("http")
        status = (
            raw_status.lower()
            if isinstance(raw_status, str)
            else ("succeeded" if looks_like_url else "pending")
        )
        if status in _TERMINAL_FAILURE_STATUSES:
            return status, None, text
        return status, (text if looks_like_url else None), None
    return "unknown", None, None


def extract_seedream_result(payload: dict[str, Any]) -> tuple[str | None, str | None]:
    """Returns `(url_or_data_uri, b64_json)` — at most one populated, both
    `None` if the response could not be parsed. This response's envelope was
    not confirmed against a live credential; tries the shapes already
    established elsewhere in this module/`aihubmix_media.py` (Responses-
    style `output[]`, and a plain OpenAI-images-style `data[]`) rather than
    betting on just one.
    """
    data = payload.get("data")
    if isinstance(data, list) and data and isinstance(data[0], dict):
        entry = data[0]
        url = entry.get("url")
        if isinstance(url, str) and url:
            return url, None
        b64 = entry.get("b64_json")
        if isinstance(b64, str) and b64:
            return None, b64
    text = _first_output_text(payload)
    if isinstance(text, str) and (text.startswith("http") or text.startswith("data:")):
        return text, None
    output = payload.get("output")
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if not isinstance(part, dict):
                    continue
                image_url = part.get("image_url")
                if isinstance(image_url, dict):
                    url = image_url.get("url")
                    if isinstance(url, str) and url:
                        return url, None
                b64 = part.get("b64_json")
                if isinstance(b64, str) and b64:
                    return None, b64
    return None, None


def _decode_data_uri(data_uri: str) -> bytes | None:
    if "," not in data_uri:
        return None
    _, _, encoded = data_uri.partition(",")
    try:
        return base64.b64decode(encoded)
    except (ValueError, TypeError):
        return None


def _probe_image_size(payload: bytes) -> tuple[int | None, int | None]:
    try:
        with Image.open(io.BytesIO(payload)) as image:
            return image.width, image.height
    except (UnidentifiedImageError, OSError):
        return None, None


def _http_error_detail(exc: httpx.HTTPStatusError, api_key: str) -> str:
    status = exc.response.status_code
    text = (exc.response.text or "").replace(api_key, "[redacted]")[:300]
    return f"HTTP {status}: {text}" if text else f"HTTP {status}"


# DMXAPI wraps a dead MiniMax/Seedance/Wan task as HTTP 502 with this code
# (live 2026-09-03: `job_01m1jjvczkcaxdgjgaetm9t9xw`, body
# `error.code=dmxapi_upstream_error` / `error.message="MiniMax-H3 video
# generation task failed"`). That is a terminal upstream verdict, not a
# one-tick gateway blip — `poll` must fail the attempt so `route_score` can
# exclude the provider. A timeout or an empty 502 still stays pending.
_DMXAPI_UPSTREAM_ERROR_CODE = "dmxapi_upstream_error"
_TERMINAL_POLL_ERROR_MARKERS = ("video generation task failed", "task failed")


def _response_json_object(response: httpx.Response) -> dict[str, Any] | None:
    try:
        payload = response.json()
    except (ValueError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


def _terminal_poll_error_message(payload: dict[str, Any]) -> str | None:
    """The user-facing upstream sentence when a poll HTTP error is terminal.

    `None` means "treat this body as a transient gateway blip" — empty,
    unparseable, or a 502 without DMXAPI's own upstream-failure shape.
    """
    error = payload.get("error")
    code: object | None
    message: str | None
    if isinstance(error, dict):
        code = error.get("code")
        raw = error.get("message")
        message = raw if isinstance(raw, str) and raw else None
    elif isinstance(error, str) and error:
        code = payload.get("code")
        message = error
    else:
        code = payload.get("code")
        raw = payload.get("message")
        message = raw if isinstance(raw, str) and raw else None
    lowered = message.lower() if message else ""
    code_hit = code == _DMXAPI_UPSTREAM_ERROR_CODE
    message_hit = any(marker in lowered for marker in _TERMINAL_POLL_ERROR_MARKERS)
    if code_hit or message_hit:
        return message or str(code)
    return None


@dataclass(frozen=True, slots=True)
class _EndpointCredentials:
    base_url: str
    api_key: str
    timeout_s: float


class DmxApiMediaProvider(GenerationProvider):
    """One media capability of one `llm_providers` endpoint, `protocol="dmxapi"`.

    One instance is bound to exactly one (endpoint, capability) pair, same
    convention as `AiHubMixMediaProvider` — see that class's docstring.
    """

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
        self._model = model
        self._creds = _EndpointCredentials(
            base_url=base_url.rstrip("/"), api_key=api_key, timeout_s=timeout_ms / 1000
        )

    def submit(self, request: GenerationRequest) -> GenerationResult:
        started = time.perf_counter()
        try:
            if self._model in _IMAGE_MODELS:
                return self._submit_image(request, started)
            if self._model in _AUDIO_MODELS:
                return self._submit_audio(request, started)
            if self._model in _MUSIC_MODELS:
                return self._submit_music(request, started)
            return self._submit_video(request, started)
        except httpx.TimeoutException as exc:
            logger.warning(
                "dmxapi %s call timed out for job %s after %.0fs: %s",
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
                "dmxapi %s call failed for job %s: HTTP %s",
                self._capability_tag,
                request.job_id,
                exc.response.status_code,
            )
            status = exc.response.status_code
            code = "PROVIDER_INVALID_RESPONSE" if status < 500 else "PROVIDER_TEMPORARY_FAILURE"
            return self._failure(started, code, _http_error_detail(exc, self._creds.api_key))
        except httpx.HTTPError as exc:
            logger.warning(
                "dmxapi %s call failed for job %s: %s", self._capability_tag, request.job_id, exc
            )
            return self._failure(started, "PROVIDER_TEMPORARY_FAILURE", type(exc).__name__)

    def _submit_video(self, request: GenerationRequest, started: float) -> GenerationResult:
        body = _build_video_body(self._model, request)
        with self._client() as client:
            response = client.post(
                media_request_path(self._creds.base_url, "/v1/responses"), json=body
            )
            response.raise_for_status()
            payload = response.json()

        task_id = extract_task_id(self._model, payload)
        if not task_id:
            return self._failure(started, "PROVIDER_INVALID_RESPONSE", "missing_task_id")

        return GenerationResult(
            succeeded=False,
            pending=True,
            mime_type="video/mp4",
            duration_ms=request.duration_seconds * 1000,
            latency_ms=self._elapsed_ms(started),
            external_task_id=task_id,
            metadata={"provider": self.name, "model": self._model},
        )

    def _submit_image(self, request: GenerationRequest, started: float) -> GenerationResult:
        body = _build_seedream_body(request)
        with self._client() as client:
            response = client.post(
                media_request_path(self._creds.base_url, "/v1/responses"), json=body
            )
            response.raise_for_status()
            payload = response.json()

        url, b64 = extract_seedream_result(payload)
        image_bytes: bytes | None = None
        if b64:
            try:
                image_bytes = base64.b64decode(b64)
            except (ValueError, TypeError):
                image_bytes = None
        elif url and url.startswith("data:"):
            image_bytes = _decode_data_uri(url)
        elif url:
            # A bare, header-less client: this response's image URL is very
            # likely a pre-signed cloud-storage link, same reasoning as
            # `aihubmix_media._submit_qwen_image_edit`'s BCE download — a
            # stray `Authorization` header can make some signed-URL edges
            # reject an otherwise-valid request.
            with httpx.Client(timeout=self._creds.timeout_s) as download_client:
                download = download_client.get(url)
                download.raise_for_status()
                image_bytes = download.content or None

        if not image_bytes:
            return self._failure(started, "PROVIDER_INVALID_RESPONSE", "missing_image")

        width, height = _probe_image_size(image_bytes)
        object_key = f"generated/{request.job_id}/output_{request.attempt_number}.png"
        s3.put_object(object_key, image_bytes, content_type="image/png")

        return GenerationResult(
            succeeded=True,
            object_key=object_key,
            mime_type="image/png",
            width=width,
            height=height,
            latency_ms=self._elapsed_ms(started),
            metadata={"provider": self.name, "model": self._model},
        )

    def _submit_audio(self, request: GenerationRequest, started: float) -> GenerationResult:
        """Synchronous TTS, same `/v1/audio/speech` contract as
        `aihubmix_media.AiHubMixMediaProvider._submit_audio` — see the
        `_AUDIO_MODELS` docstring above for why this provider doesn't
        distinguish the OpenAI-shaped group from `tts-pro` beyond the one
        extra `emotion` field.
        """
        voice = request.extra.get("voice") or _DEFAULT_VOICE_BY_MODEL[self._model]
        body: dict[str, Any] = {
            "model": self._model,
            "input": request.prompt,
            "voice": voice,
            "response_format": "mp3",
        }
        if self._model == AUDIO_MODEL_TTS_PRO:
            emotion = request.extra.get("emotion")
            if emotion:
                body["emotion"] = emotion
        with self._client() as client:
            response = client.post(
                media_request_path(self._creds.base_url, "/v1/audio/speech"), json=body
            )
            response.raise_for_status()
            audio_bytes = response.content

        object_key = f"generated/{request.job_id}/output_{request.attempt_number}.mp3"
        s3.put_object(object_key, audio_bytes, content_type="audio/mpeg")

        return GenerationResult(
            succeeded=True,
            object_key=object_key,
            mime_type="audio/mpeg",
            duration_ms=probe_audio_duration_ms(audio_bytes, "audio/mpeg"),
            latency_ms=self._elapsed_ms(started),
            metadata={"provider": self.name, "model": self._model, "voice": voice},
        )

    def _submit_music(self, request: GenerationRequest, started: float) -> GenerationResult:
        """Synchronous music generation on the shared `/v1/responses`
        envelope — same transport as `_submit_video`, but `music-3.0`
        answers with the finished clip directly instead of a task id to
        poll, the same "synchronous family riding the async envelope" shape
        `_submit_image`'s Seedream already uses on this protocol.
        """
        body = _build_music_body(request)
        with self._client() as client:
            response = client.post(
                media_request_path(self._creds.base_url, "/v1/responses"), json=body
            )
            response.raise_for_status()
            payload = response.json()

        url, duration_ms = extract_music_result(payload)
        if not url:
            return self._failure(started, "PROVIDER_INVALID_RESPONSE", "missing_audio_url")

        with httpx.Client(timeout=self._creds.timeout_s) as download_client:
            download = download_client.get(url)
            download.raise_for_status()
            audio_bytes = download.content or None
        if not audio_bytes:
            return self._failure(started, "PROVIDER_INVALID_RESPONSE", "empty_audio_content")

        object_key = f"generated/{request.job_id}/output_{request.attempt_number}.mp3"
        s3.put_object(object_key, audio_bytes, content_type="audio/mpeg")

        return GenerationResult(
            succeeded=True,
            object_key=object_key,
            mime_type="audio/mpeg",
            duration_ms=duration_ms or probe_audio_duration_ms(audio_bytes, "audio/mpeg"),
            latency_ms=self._elapsed_ms(started),
            metadata={"provider": self.name, "model": self._model},
        )

    def poll(self, external_task_id: str, request: GenerationRequest) -> GenerationResult:
        """One status check for a video task, plus the download when it is
        done — same single-round-trip-no-sleeping contract as
        `AiHubMixMediaProvider.poll`. Never called for `_IMAGE_MODELS`/
        `_AUDIO_MODELS`/`_MUSIC_MODELS`: a synchronous `submit()` never
        returns `pending=True` for those.
        """
        started = time.perf_counter()
        poll_model = _POLL_MODEL_BY_VIDEO_MODEL.get(self._model)
        if poll_model is None:
            return self._failure(
                started, "PROVIDER_POLL_UNSUPPORTED", f"no poll model for {self._model}"
            )
        try:
            with self._client() as client:
                response = client.post(
                    media_request_path(self._creds.base_url, "/v1/responses"),
                    json={"model": poll_model, "input": external_task_id},
                )
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPStatusError as exc:
            detail = _http_error_detail(exc, self._creds.api_key)
            logger.warning("dmxapi poll failed for task %s: %s", external_task_id, detail)
            payload = _response_json_object(exc.response)
            terminal = _terminal_poll_error_message(payload) if payload else None
            if terminal:
                return self._failure(started, "PROVIDER_TASK_FAILED", terminal)
            return GenerationResult(
                succeeded=False,
                pending=True,
                external_task_id=external_task_id,
                latency_ms=self._elapsed_ms(started),
                metadata={"provider": self.name, "detail": type(exc).__name__},
            )
        except httpx.HTTPError as exc:
            logger.warning("dmxapi poll failed for task %s: %s", external_task_id, exc)
            # A transient network error must not end the render: report it as
            # still pending so the next tick tries again.
            return GenerationResult(
                succeeded=False,
                pending=True,
                external_task_id=external_task_id,
                latency_ms=self._elapsed_ms(started),
                metadata={"provider": self.name, "detail": type(exc).__name__},
            )

        status, video_url, error_message = _poll_result(self._model, payload)
        if status not in _TERMINAL_STATUSES:
            return GenerationResult(
                succeeded=False,
                pending=True,
                external_task_id=external_task_id,
                latency_ms=self._elapsed_ms(started),
                metadata={"provider": self.name, "status": status},
            )
        if status in _TERMINAL_FAILURE_STATUSES or not video_url:
            return self._failure(started, "PROVIDER_TASK_FAILED", str(error_message or status))

        try:
            # Header-less on purpose — see `_submit_image`'s note on why a
            # stray `Authorization` header risks a signed-URL rejection.
            with httpx.Client(timeout=self._creds.timeout_s) as download_client:
                download = download_client.get(video_url)
                download.raise_for_status()
                video_bytes = download.content or None
        except httpx.HTTPError as exc:
            logger.warning("dmxapi video download failed for task %s: %s", external_task_id, exc)
            return GenerationResult(
                succeeded=False,
                pending=True,
                external_task_id=external_task_id,
                latency_ms=self._elapsed_ms(started),
                metadata={"provider": self.name, "detail": type(exc).__name__},
            )

        if not video_bytes:
            return self._failure(started, "PROVIDER_INVALID_RESPONSE", "empty_video_content")

        object_key = f"generated/{request.job_id}/output_{request.attempt_number}.mp4"
        s3.put_object(object_key, video_bytes, content_type="video/mp4")

        return GenerationResult(
            succeeded=True,
            object_key=object_key,
            mime_type="video/mp4",
            duration_ms=request.duration_seconds * 1000,
            latency_ms=self._elapsed_ms(started),
            external_task_id=external_task_id,
            metadata={"provider": self.name, "model": self._model, "upstream_status": status},
        )

    def cancel(self, external_task_id: str) -> bool:
        # No `cancel` endpoint is documented for any DMXAPI model this
        # provider speaks — same conservative "not supported" answer
        # `AiHubMixMediaProvider` gives for its own undocumented tracks.
        return False

    def _client(self) -> httpx.Client:
        return httpx.Client(
            base_url=media_client_base(self._creds.base_url),
            headers={"Authorization": f"Bearer {self._creds.api_key}"},
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
