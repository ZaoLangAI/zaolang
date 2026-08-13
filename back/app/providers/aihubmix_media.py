"""AiHubMix-style HTTP media provider.

The first *real* generation provider — every other one in `app/providers/` is
a fake that never leaves the process. Image and audio calls are synchronous
OpenAI-compatible HTTP requests; video calls are asynchronous: create a task,
poll it, then download the finished file once it completes.

One instance is bound to exactly one (endpoint, capability) pair. That keeps
`ProviderAttempt.provider`/the router's catalog key one-to-one, so per-model
statistics accumulate independently even when two capabilities share the same
credential — see `app/agents/router.py:build_catalog`.
"""

from __future__ import annotations

import base64
import io
import logging
import time
from dataclasses import dataclass

import httpx
from PIL import Image, UnidentifiedImageError

from app.models.enums import Operation
from app.providers.base import (
    GenerationProvider,
    GenerationRequest,
    GenerationResult,
    ProviderReference,
)
from app.storage import s3

logger = logging.getLogger(__name__)

_VIDEO_OPERATIONS = frozenset(
    {Operation.TEXT_TO_VIDEO.value, Operation.IMAGE_TO_VIDEO.value, Operation.VIDEO_TO_VIDEO.value}
)

MINIMAX_H3_MODEL = "minimax-h3"
H3_RESOLUTION = "2K"
H3_MIN_DURATION_SECONDS = 4
H3_MAX_DURATION_SECONDS = 15
H3_ASPECT_RATIOS = frozenset({"16:9", "9:16", "1:1", "4:3", "3:4", "21:9"})

# AiHubMix accepts at most nine reference images per task and rejects the
# whole request if given more.
_MAX_INPUT_REFERENCES = 9
# Anything else non-terminal is treated as "still working".
_TASK_FAILED_STATUSES = frozenset({"failed", "cancelled", "canceled", "expired"})
# How long a reference image's signed URL must stay valid. Comfortably beyond
# `app.domain.jobs.async_tasks.TASK_TIMEOUT_SECONDS`, the point at which the
# platform gives up on a render — a URL that expired while the render was
# still legitimately running would fail the task for the wrong reason.
_REFERENCE_URL_TTL_SECONDS = 900

# OpenAI-compatible gateways (and AiHubMix's Qwen list) reject sizes below a
# 512px floor. Preview used to emit `512x288` for 16:9, which is not a legal
# generations size.
_IMAGE_SIZE_BY_ASPECT = {
    "16:9": "1024x576",
    "9:16": "576x1024",
    "1:1": "1024x1024",
    "4:3": "1024x768",
    "3:4": "768x1024",
    "21:9": "1024x576",
}


def join_media_url(base_url: str, path: str) -> str:
    """Join a rooted media path onto a gateway base without doubling `/v1`.

    Operators often save chat-compatible bases as `https://host/v1`. httpx
    then turns `POST /v1/images/generations` into `/v1/v1/images/generations`
    (404). MiniMax bases are the host root and paths start with `/ai/v1/…`.
    """
    base = httpx.URL(base_url)
    path = "/" + path.lstrip("/")
    base_path = (base.path or "").rstrip("/")
    if path.startswith("/v1/") and base_path.endswith("/v1"):
        merged = base_path + path[3:]
    elif not base_path or base_path == "/":
        merged = path
    else:
        merged = base_path + path
    return str(base.copy_with(path=merged, query=None, fragment=None))


def media_client_base(base_url: str) -> str:
    """Origin only, so rooted paths are joined against the host, not `/v1`."""
    url = httpx.URL(base_url)
    return str(url.copy_with(path="/", query=None, fragment=None)).rstrip("/")


def media_request_path(base_url: str, path: str) -> str:
    return httpx.URL(join_media_url(base_url, path)).path or path


@dataclass(frozen=True, slots=True)
class _EndpointCredentials:
    base_url: str
    api_key: str
    timeout_s: float


class AiHubMixMediaProvider(GenerationProvider):
    """One media capability of one `llm_providers` endpoint."""

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
            if self._capability_tag == Operation.AUDIO_GENERATION.value:
                return self._submit_audio(request, started)
            if self._capability_tag in {
                Operation.TEXT_TO_IMAGE.value,
                Operation.IMAGE_TO_IMAGE.value,
            }:
                return self._submit_image(request, started)
            return self._submit_video(request, started)
        except httpx.TimeoutException as exc:
            logger.warning(
                "aihubmix %s call timed out for job %s after %.0fs: %s",
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
                "aihubmix %s call failed for job %s: HTTP %s",
                self._capability_tag,
                request.job_id,
                exc.response.status_code,
            )
            status = exc.response.status_code
            code = "PROVIDER_INVALID_RESPONSE" if status < 500 else "PROVIDER_TEMPORARY_FAILURE"
            return self._failure(started, code, _http_error_detail(exc, self._creds.api_key))
        except httpx.HTTPError as exc:
            logger.warning(
                "aihubmix %s call failed for job %s: %s", self._capability_tag, request.job_id, exc
            )
            return self._failure(started, "PROVIDER_TEMPORARY_FAILURE", type(exc).__name__)

    # -- image: text_to_image / image_to_image -----------------------------

    def _submit_image(self, request: GenerationRequest, started: float) -> GenerationResult:
        size = _size_for(request.aspect_ratio, request.quality_tier)
        body: dict[str, object] = {
            "model": self._model,
            "prompt": request.prompt,
            "size": size,
            "n": 1,
        }
        image_refs = _image_reference_urls(request)
        if image_refs:
            body["image"] = image_refs[0] if len(image_refs) == 1 else image_refs

        with self._client() as client:
            response = client.post(
                media_request_path(self._creds.base_url, "/v1/images/generations"), json=body
            )
            response.raise_for_status()
            payload = response.json()
            image_bytes = _image_bytes_from_payload(payload, client)

        if not image_bytes:
            return self._failure(started, "PROVIDER_INVALID_RESPONSE", "missing_image")

        width, height = _probe_image_size(image_bytes)
        object_key = f"generated/{request.job_id}/output.png"
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

    # -- audio: audio_generation ---------------------------------------------

    def _submit_audio(self, request: GenerationRequest, started: float) -> GenerationResult:
        voice = request.extra.get("voice", "alloy")
        with self._client() as client:
            response = client.post(
                media_request_path(self._creds.base_url, "/v1/audio/speech"),
                json={
                    "model": self._model,
                    "input": request.prompt,
                    "voice": voice,
                    "response_format": "mp3",
                },
            )
            response.raise_for_status()
            audio_bytes = response.content

        object_key = f"generated/{request.job_id}/output.mp3"
        s3.put_object(object_key, audio_bytes, content_type="audio/mpeg")

        return GenerationResult(
            succeeded=True,
            object_key=object_key,
            mime_type="audio/mpeg",
            latency_ms=self._elapsed_ms(started),
            metadata={"provider": self.name, "model": self._model, "voice": voice},
        )

    # -- video: text_to_video / image_to_video / video_to_video -------------

    def _submit_video(self, request: GenerationRequest, started: float) -> GenerationResult:
        """Creates the render task and returns immediately.

        A render runs for minutes. Waiting for it here would pin a worker for
        the whole time and, worse, leave the job's event stream silent until
        the very end — the user would watch one status until it suddenly
        jumped to done. `app.workers.tasks.poll_async_provider_tasks` takes it
        from here, writing a heartbeat on every check.
        """
        references = list(request.references)
        if not references and request.reference_object_keys:
            references = [
                ProviderReference(object_key=key, media_type="image")
                for key in request.reference_object_keys
            ]
        body = build_video_payload(
            model=self._model,
            prompt=request.prompt,
            duration_seconds=request.duration_seconds,
            aspect_ratio=request.aspect_ratio,
            seed=request.seed,
            references=references,
        )

        with self._client() as client:
            create = client.post(
                media_request_path(self._creds.base_url, "/ai/v1/videos"), json=body
            )
            create.raise_for_status()
            task_id = create.json().get("id")

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
        """One status check for a video task, plus the download when it is done.

        Deliberately a single round trip with no sleeping: the caller is a
        scheduler tick that must stay short, and how often to come back is
        its decision, not this method's. The caller keeps polling while this
        returns `pending`; it does not invent a timeout on the provider's
        behalf.
        """
        started = time.perf_counter()
        try:
            with self._client() as client:
                status_response = client.get(
                    media_request_path(self._creds.base_url, f"/ai/v1/tasks/{external_task_id}")
                )
                status_response.raise_for_status()
                payload = status_response.json()
                status = str(payload.get("status") or "").lower()
                outputs = payload.get("output")

                if status != "completed" and status not in _TASK_FAILED_STATUSES:
                    return GenerationResult(
                        succeeded=False,
                        pending=True,
                        external_task_id=external_task_id,
                        latency_ms=self._elapsed_ms(started),
                        metadata={"provider": self.name, "status": status},
                    )

                if not isinstance(outputs, list) or not outputs:
                    if status in _TASK_FAILED_STATUSES:
                        return self._failure(
                            started, "PROVIDER_TASK_FAILED", str(payload.get("error") or status)
                        )
                    return self._failure(
                        started, "PROVIDER_INVALID_RESPONSE", "completed_without_output"
                    )

                content = client.get(
                    media_request_path(
                        self._creds.base_url, _content_path(external_task_id, payload)
                    )
                )
                content.raise_for_status()
                video_bytes = content.content
        except httpx.HTTPError as exc:
            logger.warning("aihubmix poll failed for task %s: %s", external_task_id, exc)
            # A transient network error must not end the render: report it as
            # still pending so the next tick tries again, and let the caller's
            # deadline be what eventually gives up.
            return GenerationResult(
                succeeded=False,
                pending=True,
                external_task_id=external_task_id,
                latency_ms=self._elapsed_ms(started),
                metadata={"provider": self.name, "detail": type(exc).__name__},
            )

        if not video_bytes:
            return self._failure(started, "PROVIDER_INVALID_RESPONSE", "empty_video_content")

        object_key = f"generated/{request.job_id}/output.mp4"
        s3.put_object(object_key, video_bytes, content_type="video/mp4")

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
                "partial_output": status != "completed",
                "upstream_status": status,
            },
        )

    def cancel(self, external_task_id: str) -> bool:
        # The supplied H3 contract documents create/status/content only.  Do
        # not invent a paid-task cancellation endpoint: a 404 here would give
        # operators false confidence that the render had stopped.
        if self._model.strip().lower() == MINIMAX_H3_MODEL:
            return False
        try:
            with self._client() as client:
                response = client.post(
                    media_request_path(
                        self._creds.base_url, f"/ai/v1/tasks/{external_task_id}/cancel"
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


def _content_path(task_id: str, payload: dict[str, object]) -> str:
    """The download URL for a finished task.

    A task that produced several outputs rejects the plain path with
    `400 result_id_required`, so the first result's id is appended when the
    status response reports more than one.
    """
    outputs = payload.get("output")
    if isinstance(outputs, list) and len(outputs) > 1:
        first = outputs[0]
        result_id = first.get("result_id") if isinstance(first, dict) else None
        if result_id:
            return f"/ai/v1/tasks/{task_id}/content/{result_id}"
    return f"/ai/v1/tasks/{task_id}/content"


def build_video_payload(
    *,
    model: str,
    prompt: str,
    duration_seconds: int,
    aspect_ratio: str,
    seed: int | None = None,
    references: list[ProviderReference] | None = None,
) -> dict[str, object]:
    """Build the one H3 request shape shared by validation and production.

    Keeping the probe on the production builder prevents the exact regression
    that caused this incident: the button used a request which omitted a
    provider-required field while the worker used another hand-written shape.
    """

    if model.strip().lower() == MINIMAX_H3_MODEL:
        if not H3_MIN_DURATION_SECONDS <= duration_seconds <= H3_MAX_DURATION_SECONDS:
            raise ValueError("minimax-h3 duration must be between 4 and 15 seconds")
        if aspect_ratio not in H3_ASPECT_RATIOS:
            raise ValueError(f"minimax-h3 aspect ratio is unsupported: {aspect_ratio}")

    body: dict[str, object] = {
        "model": model,
        "prompt": prompt,
        "duration": duration_seconds,
        "aspect_ratio": aspect_ratio,
    }
    if model.strip().lower() == MINIMAX_H3_MODEL:
        body["resolution"] = H3_RESOLUTION
    if seed is not None:
        body["seed"] = seed

    refs = list(references or [])
    frame_refs = [ref for ref in refs if ref.frame_type]
    input_refs = [ref for ref in refs if not ref.frame_type]
    if frame_refs and input_refs:
        raise ValueError("frame_images and input_references are mutually exclusive")
    if frame_refs:
        body["frame_images"] = [
            {
                "image_url": {
                    "url": s3.presign_get(ref.object_key, expires_in=_REFERENCE_URL_TTL_SECONDS)
                },
                "frame_type": ref.frame_type,
            }
            for ref in frame_refs
        ]
    elif input_refs:
        body["input_references"] = [
            {
                "type": "video_url" if ref.media_type == "video" else "image_url",
                "url": s3.presign_get(ref.object_key, expires_in=_REFERENCE_URL_TTL_SECONDS),
            }
            for ref in input_refs[:_MAX_INPUT_REFERENCES]
        ]
    return body


def _image_reference_urls(request: GenerationRequest) -> list[str]:
    """Signed GET URLs for image-to-image references.

    Text-to-image leaves this empty. Image-to-image sends the same OpenAI
    `/v1/images/generations` JSON with an extra `image` field rather than
    switching to the multipart `/v1/images/edits` path.
    """
    keys: list[str] = []
    for ref in request.references:
        if ref.media_type == "image" and ref.object_key:
            keys.append(ref.object_key)
    for key in request.reference_object_keys:
        if key not in keys:
            keys.append(key)
    return [
        s3.presign_get(key, expires_in=_REFERENCE_URL_TTL_SECONDS)
        for key in keys[:_MAX_INPUT_REFERENCES]
    ]


def _image_bytes_from_payload(payload: object, client: httpx.Client) -> bytes | None:
    """OpenAI-compatible image responses carry either `b64_json` or a `url`."""
    if not isinstance(payload, dict):
        return None
    entries = payload.get("data") or []
    if not isinstance(entries, list) or not entries or not isinstance(entries[0], dict):
        return None
    entry = entries[0]
    encoded = entry.get("b64_json")
    if isinstance(encoded, str) and encoded:
        try:
            return base64.b64decode(encoded)
        except (ValueError, TypeError):
            return None
    url = entry.get("url")
    if isinstance(url, str) and url:
        download = client.get(url)
        download.raise_for_status()
        return download.content or None
    return None


def _http_error_detail(exc: httpx.HTTPStatusError, api_key: str) -> str:
    status = exc.response.status_code
    text = (exc.response.text or "").replace(api_key, "[redacted]")[:300]
    return f"HTTP {status}: {text}" if text else f"HTTP {status}"


def _size_for(aspect_ratio: str, quality_tier: str) -> str:
    """Map aspect ratio onto a gateway-legal OpenAI size.

    `quality_tier` stays in the signature so call sites are unchanged; this
    protocol's allowed grid does not vary by preview/standard/cinematic.
    """
    _ = quality_tier
    return _IMAGE_SIZE_BY_ASPECT.get(aspect_ratio, "1024x1024")


def _probe_image_size(payload: bytes) -> tuple[int | None, int | None]:
    try:
        with Image.open(io.BytesIO(payload)) as image:
            return image.width, image.height
    except (UnidentifiedImageError, OSError):
        return None, None
