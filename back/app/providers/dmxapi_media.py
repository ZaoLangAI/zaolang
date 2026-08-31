"""DMXAPI media provider.

DMXAPI aggregates many upstream vendors (MiniMax, ByteDance Doubao, Alibaba
Wan/DashScope, ...) behind one unified HTTP contract: every model this
provider speaks — synchronous image generation
(`doubao-seedream-5-0-pro-260628`) and submit-task-then-poll video generation
(`MiniMax-H3`, its video-regeneration mode, `doubao-seedance-2-5-260628`,
`wan3.0-video`) — goes through a single `POST /v1/responses` endpoint. That
is DMXAPI's own repurposing of the OpenAI "Responses API" shape as a generic
task envelope, not the real OpenAI Responses API; the request/response
*body* shape is different for every model family, so this provider
dispatches internally by `model`, the same way `AiHubMixMediaProvider`
dispatches by `capability_tag`/`protocol`.

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


def _frame_image_items(request: GenerationRequest) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for ref in request.references:
        if ref.media_type == "image" and ref.frame_type in _FRAME_ROLES:
            items.append(
                {
                    "image_url": {
                        "url": s3.presign_get(ref.object_key, expires_in=_REFERENCE_URL_TTL_SECONDS)
                    },
                    "frame_type": ref.frame_type,
                }
            )
    return items


def _input_reference_items(request: GenerationRequest) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for ref in request.references:
        if ref.frame_type in _FRAME_ROLES or ref.frame_type == "base_video":
            continue
        items.append(
            {
                "type": f"{ref.media_type}_url",
                "url": s3.presign_get(ref.object_key, expires_in=_REFERENCE_URL_TTL_SECONDS),
            }
        )
    return items


def _build_seedance_25_video_body(request: GenerationRequest) -> dict[str, Any]:
    """DMXAPI's own doc page for this model only demonstrated the pure-text
    case (`input` holding one `{"type": "text", ...}` item). ByteDance's
    underlying Seedance contract — mirrored by AiHubMix's confirmed schema
    for the same model id, see `aihubmix_media.py`'s
    `DOUBAO_SEEDANCE_25_MODEL` profile — additionally exposes first/last-
    frame and multi-modal-reference fields alongside `input`, so this
    attaches them the same way AiHubMix's `build_video_payload` does.
    **Unverified against a live DMXAPI credential.**
    """
    profile = _validate_video_request(DOUBAO_SEEDANCE_25_MODEL, request)
    body: dict[str, Any] = {
        "model": DOUBAO_SEEDANCE_25_MODEL,
        "input": [{"type": "text", "text": request.prompt}],
        "duration": request.duration_seconds,
        "ratio": request.aspect_ratio,
    }
    resolution = request.resolution or (profile.default_resolution if profile else None)
    if resolution:
        body["resolution"] = resolution
    generate_audio = request.extra.get("generate_audio")
    if generate_audio is not None:
        body["generate_audio"] = generate_audio
    frame_images = _frame_image_items(request)
    input_references = _input_reference_items(request)
    if frame_images and input_references:
        raise ValueError("frame_images and input_references are mutually exclusive")
    if frame_images:
        body["frame_images"] = frame_images
    elif input_references:
        body["input_references"] = input_references
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

    def poll(self, external_task_id: str, request: GenerationRequest) -> GenerationResult:
        """One status check for a video task, plus the download when it is
        done — same single-round-trip-no-sleeping contract as
        `AiHubMixMediaProvider.poll`. Never called for `_IMAGE_MODELS`: a
        synchronous `submit()` never returns `pending=True` for those.
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
