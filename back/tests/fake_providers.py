"""Deterministic media providers used only by tests."""

from __future__ import annotations

import hashlib
import io
import time
from typing import Any

from PIL import Image, ImageDraw

from app.providers.base import GenerationProvider, GenerationRequest, GenerationResult
from app.storage.s3 import put_object

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


def _reference_metadata(request: GenerationRequest) -> dict[str, Any]:
    voice_profiles = request.extra.get("character_voice_profiles")
    return {
        "reference_count": len(request.reference_object_keys),
        "voice_profiles": voice_profiles if voice_profiles else None,
    }


def _render_placeholder(request: GenerationRequest) -> bytes:
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
        object_key = f"generated/{request.job_id}/output_{request.attempt_number}.png"
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
            metadata={
                "provider": self.name,
                "workflow": "comfy-sdxl-base@1.4.0",
                **_reference_metadata(request),
            },
        )


class FakePaidApiProvider(GenerationProvider):
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
        suffix = "poster" if is_video else "output"
        object_key = f"generated/{request.job_id}/{suffix}_{request.attempt_number}.png"
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
            metadata={
                "provider": self.name,
                "model": "paid-video-v3",
                **_reference_metadata(request),
            },
        )


class FakeCameraApiProvider(FakePaidApiProvider):
    """A camera-control image route (stands in for fal's multi-angle LoRA):
    records the pose it was asked for so tests can assert each pass got its
    own."""

    name = "fake_camera_api"

    def submit(self, request: GenerationRequest) -> GenerationResult:
        result = super().submit(request)
        pose = (request.extra or {}).get("camera_pose")
        if result.succeeded:
            result.metadata["camera_pose"] = dict(pose) if isinstance(pose, dict) else None
            result.metadata["model"] = "fake-multi-angle"
        return result


class FakeVideoAnalysisProvider(GenerationProvider):
    """`video_analysis`'s own shape: `output_json`, never `object_key`."""

    name = "fake_video_analysis"
    kind = "commercial_api"
    base_latency_ms = 1_500
    unit_cost_minor = 12

    def submit(self, request: GenerationRequest) -> GenerationResult:
        started = time.perf_counter()
        if FORCE_FAILURE_MARKER in request.prompt:
            return GenerationResult(
                succeeded=False,
                failure_code="PROVIDER_TEMPORARY_FAILURE",
                latency_ms=int((time.perf_counter() - started) * 1000),
                metadata={"provider": self.name, "simulated": True},
            )
        return GenerationResult(
            succeeded=True,
            output_json={
                "summary": "测试摘要：一段海边的黄昏长镜头。",
                "composed_prompt": "海边黄昏，长镜头缓慢推进，暖色调。",
                "style_tags": ["长镜头", "暖色调"],
                "pacing": "舒缓长镜头",
                "shots": [
                    {
                        "time_range": "00:00-00:05",
                        "camera_movement": "推镜",
                        "scene": "海边",
                        "subject_action": "缓慢前行",
                        "lighting_mood": "黄昏暖光",
                        "transition_in": "淡入",
                    }
                ],
            },
            cost_minor=self.unit_cost_minor,
            latency_ms=int((time.perf_counter() - started) * 1000) + self.base_latency_ms,
            external_task_id=f"analysis-{_seeded(request.job_id, 'task'):08x}",
            metadata={"provider": self.name, "model": "fake-video-understanding-v1"},
        )


REGISTRY: dict[str, GenerationProvider] = {
    FakeOpenWorkflowProvider.name: FakeOpenWorkflowProvider(),
    FakePaidApiProvider.name: FakePaidApiProvider(),
    FakeVideoAnalysisProvider.name: FakeVideoAnalysisProvider(),
    FakeCameraApiProvider.name: FakeCameraApiProvider(),
}


def get_provider(name: str) -> GenerationProvider:
    """A process-wide singleton per name — `ProviderCapability
    .provider_factory` is called fresh on every access of `RoutingDecision
    .provider` (see `app.agents.router`), so a test that reads `.provider`
    more than once within the same test (grab the original `submit`, patch
    it, then let the pipeline call it) needs every access to resolve to the
    *same* object.

    Because of that, **a test must always monkeypatch `submit` on the
    class** (e.g. `type(get_provider("fake_open_workflow"))`), never on a
    `get_provider(...)` return value directly: `submit` only exists on the
    class, so patching an instance makes `monkeypatch`'s own teardown
    snapshot the class-inherited bound method and re-`setattr` it back as a
    *new instance attribute* — permanently shadowing the class for this
    singleton, for the rest of the test session. Every later test's own
    class-level `submit` patch then silently has no effect on it (a
    "failed" provider call quietly runs the real, un-monkeypatched
    implementation instead and succeeds).
    """
    provider = REGISTRY.get(name)
    if provider is None:
        raise KeyError(f"未注册的测试供应商: {name}")
    return provider
