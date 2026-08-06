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
from app.providers.base import GenerationProvider, GenerationRequest, GenerationResult
from app.storage import s3

logger = logging.getLogger(__name__)

_VIDEO_OPERATIONS = frozenset(
    {Operation.TEXT_TO_VIDEO.value, Operation.IMAGE_TO_VIDEO.value, Operation.VIDEO_TO_VIDEO.value}
)

# Polling cadence and ceiling for the async video contract. A render that has
# not finished within this window is presumed stuck, not merely slow — the
# job fails and the user can retry rather than the worker blocking forever.
_VIDEO_POLL_INTERVAL_SECONDS = 15
_VIDEO_POLL_TIMEOUT_SECONDS = 480
# How long a reference image's signed URL must stay valid: the whole poll
# window plus slack for AiHubMix to actually fetch it.
_REFERENCE_URL_TTL_SECONDS = _VIDEO_POLL_TIMEOUT_SECONDS + 300


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
        except httpx.HTTPError as exc:
            logger.warning(
                "aihubmix %s call failed for job %s: %s", self._capability_tag, request.job_id, exc
            )
            return self._failure(started, "PROVIDER_TEMPORARY_FAILURE", type(exc).__name__)

    # -- image: text_to_image / image_to_image -----------------------------

    def _submit_image(self, request: GenerationRequest, started: float) -> GenerationResult:
        size = _size_for(request.aspect_ratio, request.quality_tier)
        with self._client() as client:
            if request.reference_object_keys:
                reference = s3.get_object(request.reference_object_keys[0])
                files = {"image": ("reference.png", reference, "image/png")}
                data = {"model": self._model, "prompt": request.prompt, "size": size, "n": "1"}
                response = client.post("/v1/images/edits", data=data, files=files)
            else:
                response = client.post(
                    "/v1/images/generations",
                    json={"model": self._model, "prompt": request.prompt, "size": size, "n": 1},
                )
            response.raise_for_status()
            payload = response.json()

        entries = payload.get("data") or []
        if not entries or "b64_json" not in entries[0]:
            return self._failure(started, "PROVIDER_INVALID_RESPONSE", "missing_b64_json")

        image_bytes = base64.b64decode(entries[0]["b64_json"])
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
                "/v1/audio/speech",
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
        body: dict[str, object] = {
            "model": self._model,
            "prompt": request.prompt,
            "duration": request.duration_seconds,
            "aspect_ratio": request.aspect_ratio,
        }
        if request.seed is not None:
            body["seed"] = request.seed
        if request.reference_object_keys:
            body["input_references"] = [
                s3.presign_get(key, expires_in=_REFERENCE_URL_TTL_SECONDS)
                for key in request.reference_object_keys
            ]

        with self._client() as client:
            create = client.post("/ai/v1/videos", json=body)
            create.raise_for_status()
            task_id = create.json().get("task_id")
            if not task_id:
                return self._failure(started, "PROVIDER_INVALID_RESPONSE", "missing_task_id")

            deadline = time.monotonic() + _VIDEO_POLL_TIMEOUT_SECONDS
            while True:
                status_response = client.get(f"/ai/v1/tasks/{task_id}")
                status_response.raise_for_status()
                status_payload = status_response.json()
                status = status_payload.get("status")

                if status == "completed":
                    break
                if status == "failed":
                    return self._failure(
                        started, "PROVIDER_TASK_FAILED", str(status_payload.get("error") or "")
                    )
                if time.monotonic() >= deadline:
                    return self._failure(started, "PROVIDER_TIMEOUT", f"task {task_id} timed out")
                time.sleep(_VIDEO_POLL_INTERVAL_SECONDS)

            content = client.get(f"/ai/v1/tasks/{task_id}/content")
            content.raise_for_status()
            video_bytes = content.content

        object_key = f"generated/{request.job_id}/output.mp4"
        s3.put_object(object_key, video_bytes, content_type="video/mp4")

        return GenerationResult(
            succeeded=True,
            object_key=object_key,
            mime_type="video/mp4",
            duration_ms=request.duration_seconds * 1000,
            latency_ms=self._elapsed_ms(started),
            external_task_id=task_id,
            metadata={"provider": self.name, "model": self._model},
        )

    def cancel(self, external_task_id: str) -> bool:
        try:
            with self._client() as client:
                response = client.post(f"/ai/v1/tasks/{external_task_id}/cancel")
                return response.status_code < 400
        except httpx.HTTPError:
            return False

    def _client(self) -> httpx.Client:
        return httpx.Client(
            base_url=self._creds.base_url,
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


def _size_for(aspect_ratio: str, quality_tier: str) -> str:
    base = {"preview": 512, "standard": 896, "cinematic": 1280}.get(quality_tier, 896)
    try:
        w_ratio, h_ratio = (int(part) for part in aspect_ratio.split(":"))
    except ValueError:
        w_ratio, h_ratio = 16, 9
    if w_ratio >= h_ratio:
        width, height = base, max(64, base * h_ratio // w_ratio)
    else:
        width, height = max(64, base * w_ratio // h_ratio), base
    return f"{width}x{height}"


def _probe_image_size(payload: bytes) -> tuple[int | None, int | None]:
    try:
        with Image.open(io.BytesIO(payload)) as image:
            return image.width, image.height
    except (UnidentifiedImageError, OSError):
        return None, None
