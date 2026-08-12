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
            unit_cost_minor=2,
            model_or_workflow="comfy-sdxl-base@1.4.0",
            provider_factory=lambda: fake_providers.get_provider("fake_open_workflow"),
        ),
        "fake_paid_api": ProviderCapability(
            name="fake_paid_api",
            kind=ProviderKind.COMMERCIAL_API,
            operations=frozenset(
                {
                    Operation.TEXT_TO_IMAGE,
                    Operation.TEXT_TO_VIDEO,
                    Operation.IMAGE_TO_VIDEO,
                    Operation.VIDEO_TO_VIDEO,
                }
            ),
            tiers=frozenset({QualityTier.PREVIEW, QualityTier.STANDARD, QualityTier.CINEMATIC}),
            quality_prior=0.9,
            typical_latency_ms=22_000,
            unit_cost_minor=18,
            model_or_workflow="paid-video-v3",
            provider_factory=lambda: fake_providers.get_provider("fake_paid_api"),
        ),
    }
