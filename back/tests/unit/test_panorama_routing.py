"""AC-7: a scene panorama (2:1) only routes to an image adapter with an exact
2:1 size — any other would quietly return a square or 16:9 image."""

from __future__ import annotations

from app.agents import router
from app.models.enums import ProviderKind
from app.providers import media_endpoints
from app.providers.base import ProviderCapability
from app.providers.dmxapi_media import SEEDREAM_5_PRO_MODEL

PANORAMA = {"scene_panorama": True, "aspect_ratio": "2:1"}


def _capability(name: str, **overrides: object) -> ProviderCapability:
    values: dict[str, object] = {
        "name": name,
        "kind": ProviderKind.COMMERCIAL_API,
        "operations": frozenset({"text_to_image"}),
        "tiers": frozenset({"standard"}),
        "quality_prior": 0.8,
        "typical_latency_ms": 1000,
        "unit_cost_micro_usd": 1,
        "model_or_workflow": name,
        "provider_factory": lambda: None,
    }
    values.update(overrides)
    return ProviderCapability(**values)  # type: ignore[arg-type]


def test_a_panorama_needs_an_exact_2_to_1_size() -> None:
    seedream = _capability("seedream", exact_image_aspect_ratios=frozenset({"16:9", "2:1"}))
    widescreen = _capability("wide", exact_image_aspect_ratios=frozenset({"16:9"}))
    unknown = _capability("unknown")
    assert router._request_constraint_failure(seedream, PANORAMA) is None
    for capability in (widescreen, unknown):
        assert (
            router._request_constraint_failure(capability, PANORAMA)
            == "panorama_size_not_supported"
        )
        # Any other image request is unaffected.
        assert router._request_constraint_failure(capability, {"aspect_ratio": "2:1"}) is None


def test_only_seedream_advertises_a_2_to_1_size() -> None:
    sizes = media_endpoints._exact_image_aspect_ratios(
        "dmxapi", SEEDREAM_5_PRO_MODEL, "text_to_image"
    )
    assert sizes is not None and "2:1" in sizes
    assert (
        media_endpoints._exact_image_aspect_ratios("aihubmix", "gpt-image-2", "text_to_image")
        is None
    )
    assert (
        media_endpoints._exact_image_aspect_ratios("dmxapi", SEEDREAM_5_PRO_MODEL, "text_to_video")
        is None
    )
