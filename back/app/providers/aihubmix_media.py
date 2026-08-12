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
            create = client.post("/ai/v1/videos", json=body)
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
        its decision, not this method's. The overall deadline is enforced by
        the caller too, which is the only side that knows when the task was
        created.
        """
        started = time.perf_counter()
        try:
            with self._client() as client:
                status_response = client.get(f"/ai/v1/tasks/{external_task_id}")
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

                content = client.get(_content_path(external_task_id, payload))
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
