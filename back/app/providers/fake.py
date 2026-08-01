"""Deterministic stand-in providers.

They render a real image or video file so the whole pipeline — upload, probe,
fingerprint, thumbnail, playback — is exercised end to end. Behaviour is keyed
by a hash of the job id, so a given job always behaves the same way and tests
can pick an id that reproduces a failure.
"""

from __future__ import annotations

import hashlib
import io
import time

from PIL import Image, ImageDraw

from app.providers.base import GenerationProvider, GenerationRequest, GenerationResult
from app.storage.s3 import put_object

# Trip codes let a test force a specific outcome without monkeypatching.
FORCE_FAILURE_MARKER = "force_provider_failure"
FORCE_SLOW_MARKER = "force_provider_slow"


def _seeded(job_id: str, salt: str) -> int:
    return int(hashlib.sha256(f"{job_id}:{salt}".encode()).hexdigest()[:8], 16)


def _palette(seed: int) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    top = ((seed >> 16) % 60 + 8, (seed >> 8) % 40 + 10, seed % 90 + 30)
    bottom = ((seed >> 4) % 90 + 40, (seed >> 12) % 60 + 20, (seed >> 20) % 120 + 80)
    return top, bottom


def _dimensions(aspect_ratio: str, tier: str) -> tuple[int, int]:
    base = {"preview": 512, "standard": 896, "cinematic": 1280}.get(tier, 896)
    try:
        w_ratio, h_ratio = (int(part) for part in aspect_ratio.split(":"))
    except ValueError:
        w_ratio, h_ratio = 16, 9
    if w_ratio >= h_ratio:
        return base, max(64, base * h_ratio // w_ratio)
    return max(64, base * w_ratio // h_ratio), base


def _render_placeholder(request: GenerationRequest) -> bytes:
    """Draws a labelled gradient so prototype output is never mistaken for a
    real generation."""
    seed = _seeded(request.job_id, "visual")
    width, height = _dimensions(request.aspect_ratio, request.quality_tier)
    top, bottom = _palette(seed)

    image = Image.new("RGB", (width, height), top)
    draw = ImageDraw.Draw(image)
    for y in range(height):
        blend = y / max(height - 1, 1)
        draw.line(
            [(0, y), (width, y)],
            fill=tuple(int(top[i] + (bottom[i] - top[i]) * blend) for i in range(3)),
        )

    label = f"PROTOTYPE · {request.operation} · {request.quality_tier}"
    draw.rectangle([(0, height - 44), (width, height)], fill=(0, 0, 0))
    draw.text((16, height - 30), label, fill=(240, 240, 240))
    draw.text((16, 16), request.prompt[:60], fill=(255, 255, 255))

    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


class FakeOpenWorkflowProvider(GenerationProvider):
    """Stands in for a self-hosted ComfyUI route: cheap, slower, image-first."""

    name = "fake_open_workflow"
    kind = "open_workflow"
    base_latency_ms = 900
    unit_cost_minor = 2

    def submit(self, request: GenerationRequest) -> GenerationResult:
        started = time.perf_counter()
        if FORCE_FAILURE_MARKER in request.prompt:
            return GenerationResult(
                succeeded=False,
                failure_code="PROVIDER_TEMPORARY_FAILURE",
                latency_ms=int((time.perf_counter() - started) * 1000),
                metadata={"provider": self.name, "simulated": True},
            )

        payload = _render_placeholder(request)
        object_key = f"generated/{request.job_id}/output.png"
        put_object(object_key, payload, content_type="image/png")
        width, height = _dimensions(request.aspect_ratio, request.quality_tier)

        return GenerationResult(
            succeeded=True,
            object_key=object_key,
            mime_type="image/png",
            width=width,
            height=height,
            cost_minor=self.unit_cost_minor,
            latency_ms=int((time.perf_counter() - started) * 1000) + self.base_latency_ms,
            external_task_id=f"open-{_seeded(request.job_id, 'task'):08x}",
            metadata={"provider": self.name, "workflow": "comfy-sdxl-base@1.4.0"},
        )


class FakePaidApiProvider(GenerationProvider):
    """Stands in for a commercial API: pricier, higher quality, does video."""

    name = "fake_paid_api"
    kind = "commercial_api"
    base_latency_ms = 2_200
    unit_cost_minor = 18

    def submit(self, request: GenerationRequest) -> GenerationResult:
        started = time.perf_counter()
        if FORCE_FAILURE_MARKER in request.prompt:
            return GenerationResult(
                succeeded=False,
                failure_code="PROVIDER_TEMPORARY_FAILURE",
                latency_ms=int((time.perf_counter() - started) * 1000),
                metadata={"provider": self.name, "simulated": True},
            )

        is_video = request.operation in {"text_to_video", "image_to_video", "video_to_video"}
        payload = _render_placeholder(request)
        suffix = "poster.png" if is_video else "output.png"
        object_key = f"generated/{request.job_id}/{suffix}"
        put_object(object_key, payload, content_type="image/png")
        width, height = _dimensions(request.aspect_ratio, request.quality_tier)

        return GenerationResult(
            succeeded=True,
            object_key=object_key,
            mime_type="image/png",
            width=width,
            height=height,
            duration_ms=request.duration_seconds * 1000 if is_video else None,
            cost_minor=self.unit_cost_minor * (2 if is_video else 1),
            latency_ms=int((time.perf_counter() - started) * 1000) + self.base_latency_ms,
            external_task_id=f"paid-{_seeded(request.job_id, 'task'):08x}",
            metadata={"provider": self.name, "model": "paid-video-v3"},
        )


REGISTRY: dict[str, GenerationProvider] = {
    FakeOpenWorkflowProvider.name: FakeOpenWorkflowProvider(),
    FakePaidApiProvider.name: FakePaidApiProvider(),
}


def get_provider(name: str) -> GenerationProvider:
    provider = REGISTRY.get(name)
    if provider is None:
        raise KeyError(f"未注册的供应商: {name}")
    return provider
