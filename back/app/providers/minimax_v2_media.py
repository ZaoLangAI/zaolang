"""Official MiniMax Video Generation V2 media provider.

Speaks `POST /v2/video_generation` + `GET /v2/query/video_generation/{id}` +
`DELETE /v2/video_generation/{id}` — MiniMax's own Video V2 contract, which
Metaso proxies at `https://metaso.cn/api/minimax`. This is a different HTTP
shape from `protocol=minimax` (AiHubMix `/ai/v1/videos` with
`prompt`/`frame_images`/`input_references`) and from `protocol=dmxapi`
(`POST /v1/responses`).

Create is documented on Metaso's product page. Query / cancel / download
are inferred from official MiniMax V2 docs and have **not** been verified
against a live Metaso credential — every response-parsing function below
tolerates a few plausible shapes rather than betting on exactly one. Fix
the specific function (not the whole module) if a real call disagrees.
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
)
from app.storage import s3

logger = logging.getLogger(__name__)

MINIMAX_H3_MODEL = "MiniMax-H3"

_TERMINAL_FAILURE_STATUSES = frozenset({"failed", "cancelled", "canceled"})
_SUCCESS_STATUSES = frozenset({"succeeded", "completed"})
_TERMINAL_STATUSES = _TERMINAL_FAILURE_STATUSES | _SUCCESS_STATUSES

_REFERENCE_URL_TTL_SECONDS = 900
_MAX_PROMPT_CHARS = 7000
_MAX_REFERENCE_IMAGES = 9
_MAX_REFERENCE_VIDEOS = 3
_MAX_REFERENCE_AUDIOS = 3
_MAX_REFERENCE_FILES = 12
_T2V_FALLBACK_RATIO = "16:9"

_FRAME_ROLES = frozenset({"first_frame", "last_frame"})
_DEFAULT_REFERENCE_ROLE = {
    "image": "reference_image",
    "video": "reference_video",
    "audio": "reference_audio",
}


@dataclass(frozen=True, slots=True)
class VideoModelProfile:
    """One official MiniMax V2 video model's physical limits."""

    min_duration_seconds: int
    max_duration_seconds: int
    aspect_ratios: frozenset[str]
    resolutions: frozenset[str]
    default_resolution: str | None
    reference_modes: frozenset[str] = field(default_factory=frozenset)


VIDEO_MODEL_PROFILES: dict[str, VideoModelProfile] = {
    MINIMAX_H3_MODEL: VideoModelProfile(
        min_duration_seconds=4,
        max_duration_seconds=15,
        aspect_ratios=frozenset({"21:9", "16:9", "4:3", "1:1", "3:4", "9:16", "adaptive"}),
        resolutions=frozenset({"768P", "2K"}),
        default_resolution="2K",
        reference_modes=frozenset({"input_references", "frame_images"}),
    ),
}


def video_model_profile(model: str) -> VideoModelProfile | None:
    """The profile for a MiniMax V2 video model, if known.

    `None` for anything not in the table — callers treat that as "no extra
    validation, no hard filter", never as "reject it".
    """
    return VIDEO_MODEL_PROFILES.get(model.strip())


def _resolved_references(request: GenerationRequest) -> list[ProviderReference]:
    refs = list(request.references)
    if not refs and request.reference_object_keys:
        refs = [
            ProviderReference(object_key=key, media_type="image")
            for key in request.reference_object_keys
        ]
    return refs


def _content_items_from_references(request: GenerationRequest) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for ref in _resolved_references(request):
        if ref.frame_type == "base_video":
            continue
        url = s3.presign_get(ref.object_key, expires_in=_REFERENCE_URL_TTL_SECONDS)
        item_type = f"{ref.media_type}_url"
        role = (
            ref.frame_type
            if ref.frame_type in _FRAME_ROLES
            else _DEFAULT_REFERENCE_ROLE.get(ref.media_type, "reference_image")
        )
        items.append({"type": item_type, item_type: {"url": url}, "role": role})
    return items


def _validate_generation_request(model: str, request: GenerationRequest) -> VideoModelProfile | None:
    profile = video_model_profile(model)
    if profile is None:
        return None
    if not profile.min_duration_seconds <= request.duration_seconds <= profile.max_duration_seconds:
        raise ValueError(
            f"{model} duration must be between {profile.min_duration_seconds} and "
            f"{profile.max_duration_seconds} seconds"
        )
    if request.aspect_ratio not in profile.aspect_ratios:
        raise ValueError(f"{model} aspect ratio is unsupported: {request.aspect_ratio}")
    if request.resolution is not None and request.resolution not in profile.resolutions:
        raise ValueError(f"{model} resolution is unsupported: {request.resolution}")
    return profile


def build_generation_body(request: GenerationRequest, *, model: str = MINIMAX_H3_MODEL) -> dict[str, Any]:
    """Official MiniMax V2 create body: `content[]` plus duration/resolution/ratio.

    Text-only (t2va): `ratio` is required and cannot be `adaptive` — a
    studio "auto" pick is remapped to 16:9 rather than sent upstream.
    First/last-frame (i2va): `ratio` is forced to `adaptive`.
    Multimodal reference (r2va): `ratio` is passed through (adaptive allowed).
    Frame roles and `reference_*` roles are mutually exclusive.
    """
    prompt = request.prompt.strip()
    if not prompt:
        raise ValueError(f"{model} requires a non-empty text prompt")
    if len(prompt) > _MAX_PROMPT_CHARS:
        raise ValueError(f"{model} prompt must be at most {_MAX_PROMPT_CHARS} characters")

    profile = _validate_generation_request(model, request)
    media_items = _content_items_from_references(request)
    roles = {item.get("role") for item in media_items}
    frame_roles = roles & _FRAME_ROLES
    reference_roles = roles - _FRAME_ROLES - {None}
    if frame_roles and reference_roles:
        raise ValueError("frame_images and input_references are mutually exclusive")

    image_count = sum(1 for item in media_items if item.get("type") == "image_url")
    video_count = sum(1 for item in media_items if item.get("type") == "video_url")
    audio_count = sum(1 for item in media_items if item.get("type") == "audio_url")
    if image_count > _MAX_REFERENCE_IMAGES:
        raise ValueError(f"{model} accepts at most {_MAX_REFERENCE_IMAGES} reference images")
    if video_count > _MAX_REFERENCE_VIDEOS:
        raise ValueError(f"{model} accepts at most {_MAX_REFERENCE_VIDEOS} reference videos")
    if audio_count > _MAX_REFERENCE_AUDIOS:
        raise ValueError(f"{model} accepts at most {_MAX_REFERENCE_AUDIOS} reference audios")
    if len(media_items) > _MAX_REFERENCE_FILES:
        raise ValueError(f"{model} accepts at most {_MAX_REFERENCE_FILES} reference files")

    if frame_roles:
        ratio = "adaptive"
    elif media_items:
        ratio = request.aspect_ratio
    elif request.aspect_ratio == "adaptive":
        ratio = _T2V_FALLBACK_RATIO
    else:
        ratio = request.aspect_ratio

    body: dict[str, Any] = {
        "model": model,
        "content": [{"type": "text", "text": prompt}, *media_items],
        "duration": request.duration_seconds,
        "ratio": ratio,
    }
    resolution = request.resolution or (profile.default_resolution if profile else None)
    if resolution:
        body["resolution"] = resolution
    return body


def probe_video_body(model: str) -> dict[str, Any]:
    """Minimal t2va body for admin connectivity — 768P / 4s / 16:9."""
    return {
        "model": model,
        "content": [{"type": "text", "text": "A static blue square, connectivity test."}],
        "duration": 4,
        "resolution": "768P",
        "ratio": "16:9",
    }


def extract_task_id(payload: dict[str, Any]) -> str | None:
    """Create response: official MiniMax V2 returns `{task_id}`; also accept
    a nested `task.id` or a top-level `id` if a proxy flattens the envelope.
    **Unverified against a live Metaso credential.**
    """
    task_id = payload.get("task_id")
    if task_id:
        return str(task_id)
    task = payload.get("task")
    if isinstance(task, dict) and task.get("id"):
        return str(task["id"])
    bare = payload.get("id")
    return str(bare) if bare else None


def _poll_result(payload: dict[str, Any]) -> tuple[str, str | None, str | None]:
    """Returns `(status, video_url_if_done, error_message_if_failed)`.

    Official query nests under `task` (`task.status` / `task.content.url` /
    `task.error`). A flattened top-level copy of those fields is also
    accepted. **Unverified against a live Metaso credential.**
    """
    task = payload.get("task")
    source = task if isinstance(task, dict) else payload
    status = str(source.get("status") or "").lower()
    content = source.get("content")
    url = content.get("url") if isinstance(content, dict) else None
    error = source.get("error")
    message = (
        error
        if isinstance(error, str)
        else (error.get("message") if isinstance(error, dict) else None)
    )
    return status, (url if isinstance(url, str) and url else None), message


def _http_error_detail(exc: httpx.HTTPStatusError, api_key: str) -> str:
    status = exc.response.status_code
    text = (exc.response.text or "").replace(api_key, "[redacted]")[:300]
    return f"HTTP {status}: {text}" if text else f"HTTP {status}"


@dataclass(frozen=True, slots=True)
class _EndpointCredentials:
    base_url: str
    api_key: str
    timeout_s: float


class MinimaxV2MediaProvider(GenerationProvider):
    """One video capability of one `protocol="minimax_v2"` media endpoint."""

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
            body = build_generation_body(request, model=self._model)
            with self._client() as client:
                response = client.post(
                    media_request_path(self._creds.base_url, "/v2/video_generation"), json=body
                )
                response.raise_for_status()
                payload = response.json()
        except ValueError as exc:
            return self._failure(started, "PROVIDER_INVALID_RESPONSE", str(exc))
        except httpx.TimeoutException as exc:
            logger.warning(
                "minimax_v2 %s call timed out for job %s after %.0fs: %s",
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
                "minimax_v2 %s call failed for job %s: HTTP %s",
                self._capability_tag,
                request.job_id,
                exc.response.status_code,
            )
            status = exc.response.status_code
            code = "PROVIDER_INVALID_RESPONSE" if status < 500 else "PROVIDER_TEMPORARY_FAILURE"
            return self._failure(started, code, _http_error_detail(exc, self._creds.api_key))
        except httpx.HTTPError as exc:
            logger.warning(
                "minimax_v2 %s call failed for job %s: %s",
                self._capability_tag,
                request.job_id,
                exc,
            )
            return self._failure(started, "PROVIDER_TEMPORARY_FAILURE", type(exc).__name__)

        if not isinstance(payload, dict):
            return self._failure(started, "PROVIDER_INVALID_RESPONSE", "missing_task_id")
        task_id = extract_task_id(payload)
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

    def poll(self, external_task_id: str, request: GenerationRequest) -> GenerationResult:
        """One query of `GET /v2/query/video_generation/{id}`, plus a
        header-less download of `task.content.url` when the task succeeded.

        **Query path inferred from official MiniMax V2, not live-confirmed
        on Metaso.** A transient HTTP error stays pending so the next Beat
        tick retries.
        """
        started = time.perf_counter()
        try:
            with self._client() as client:
                response = client.get(
                    media_request_path(
                        self._creds.base_url, f"/v2/query/video_generation/{external_task_id}"
                    )
                )
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPError as exc:
            logger.warning("minimax_v2 poll failed for task %s: %s", external_task_id, exc)
            return GenerationResult(
                succeeded=False,
                pending=True,
                external_task_id=external_task_id,
                latency_ms=self._elapsed_ms(started),
                metadata={"provider": self.name, "detail": type(exc).__name__},
            )

        if not isinstance(payload, dict):
            return self._failure(started, "PROVIDER_INVALID_RESPONSE", "invalid_poll_payload")
        status, video_url, error_message = _poll_result(payload)
        if status not in _TERMINAL_STATUSES:
            return GenerationResult(
                succeeded=False,
                pending=True,
                external_task_id=external_task_id,
                latency_ms=self._elapsed_ms(started),
                metadata={"provider": self.name, "status": status},
            )
        if status in _TERMINAL_FAILURE_STATUSES or status not in _SUCCESS_STATUSES or not video_url:
            return self._failure(started, "PROVIDER_TASK_FAILED", str(error_message or status))

        try:
            with httpx.Client(timeout=self._creds.timeout_s) as download_client:
                download = download_client.get(video_url)
                download.raise_for_status()
                video_bytes = download.content or None
        except httpx.HTTPError as exc:
            logger.warning("minimax_v2 video download failed for task %s: %s", external_task_id, exc)
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
        """`DELETE /v2/video_generation/{id}` — official V2 only cancels a
        `queued` task; `running` returns an error. A miss is logged by the
        caller and does not block the local CANCELLED transition.
        **Unverified against a live Metaso credential.**
        """
        try:
            with self._client() as client:
                response = client.delete(
                    media_request_path(
                        self._creds.base_url, f"/v2/video_generation/{external_task_id}"
                    )
                )
                return response.status_code < 400
        except httpx.HTTPError:
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
