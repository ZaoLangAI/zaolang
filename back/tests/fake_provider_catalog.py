"""Media routes injected by tests; production catalogues never include these."""

from app.models.enums import Operation, ProviderKind, QualityTier
from app.providers.base import ProviderCapability
from tests import fake_providers


def build_fake_catalog() -> dict[str, ProviderCapability]:
    return {
        "fake_open_workflow": ProviderCapability(
            name="fake_open_workflow",
            kind=ProviderKind.OPEN_WORKFLOW,
            operations=frozenset(
                {Operation.TEXT_TO_IMAGE, Operation.IMAGE_TO_VIDEO, Operation.VIDEO_TO_VIDEO}
            ),
            tiers=frozenset({QualityTier.PREVIEW, QualityTier.STANDARD}),
            quality_prior=0.72,
            typical_latency_ms=9_000,
            unit_cost_micro_usd=20000,
            model_or_workflow="comfy-sdxl-base@1.4.0",
            provider_factory=lambda: fake_providers.get_provider("fake_open_workflow"),
        ),
        "fake_paid_api": ProviderCapability(
            name="fake_paid_api",
            kind=ProviderKind.COMMERCIAL_API,
            operations=frozenset(
                {
                    Operation.TEXT_TO_IMAGE,
                    Operation.IMAGE_TO_IMAGE,
                    Operation.TEXT_TO_VIDEO,
                    Operation.IMAGE_TO_VIDEO,
                    Operation.VIDEO_TO_VIDEO,
                    Operation.AUDIO_GENERATION,
                }
            ),
            tiers=frozenset({QualityTier.PREVIEW, QualityTier.STANDARD, QualityTier.CINEMATIC}),
            quality_prior=0.9,
            typical_latency_ms=22_000,
            unit_cost_micro_usd=180000,
            model_or_workflow="paid-video-v3",
            # Takes a labelled multi-image reference set (reference legend tests).
            max_image_references=9,
            provider_factory=lambda: fake_providers.get_provider("fake_paid_api"),
        ),
        # Camera-control image route: only ever eligible for a posed pass
        # (`router._request_constraint_failure`), so it never changes routing
        # for any other test.
        "fake_camera_api": ProviderCapability(
            name="fake_camera_api",
            kind=ProviderKind.COMMERCIAL_API,
            operations=frozenset({Operation.IMAGE_TO_IMAGE}),
            tiers=frozenset({QualityTier.PREVIEW, QualityTier.STANDARD, QualityTier.CINEMATIC}),
            quality_prior=0.9,
            typical_latency_ms=12_000,
            unit_cost_micro_usd=35000,
            model_or_workflow="fake-multi-angle",
            max_image_references=1,
            camera_control=True,
            provider_factory=lambda: fake_providers.get_provider("fake_camera_api"),
        ),
        "fake_video_analysis": ProviderCapability(
            name="fake_video_analysis",
            kind=ProviderKind.COMMERCIAL_API,
            operations=frozenset({Operation.VIDEO_ANALYSIS}),
            tiers=frozenset({QualityTier.PREVIEW, QualityTier.STANDARD, QualityTier.CINEMATIC}),
            quality_prior=0.85,
            typical_latency_ms=6_000,
            unit_cost_micro_usd=90000,
            model_or_workflow="fake-video-understanding-v1",
            provider_factory=lambda: fake_providers.get_provider("fake_video_analysis"),
        ),
    }
