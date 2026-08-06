"""Builds routable capabilities from the database-configured media pool.

Kept separate from `app/agents/router.py` on purpose: the router's own test
suite asserts its source never mentions a model gateway by name, to guard the
promise that routing stays a fixed, explainable formula. This module does the
one gateway-adjacent thing the router needs — turning `llm_providers`
`kind="media"` endpoints into `ProviderCapability` entries — so the router
itself only ever imports the provider-neutral abstraction.
"""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy.orm import Session

from app.models.enums import ProviderKind
from app.platform_config import service as config_service
from app.platform_config.schemas import LlmProviderConfig
from app.providers.aihubmix_media import AiHubMixMediaProvider
from app.providers.base import GenerationProvider, ProviderCapability

# Conservative defaults for a capability with no `ProviderStat` history yet.
# Real observed latency/cost/success rate (via `router.record_attempt_outcome`)
# takes over once enough samples exist — see `router._success_rate`.
_QUALITY_PRIOR = 0.75
_TYPICAL_LATENCY_MS: dict[str, int] = {
    "text_to_image": 12_000,
    "image_to_image": 14_000,
    "audio_generation": 6_000,
    "text_to_video": 90_000,
    "image_to_video": 90_000,
    "video_to_video": 100_000,
}
# Minor-currency (matches `unit_cost_minor` elsewhere) rough per-call cost,
# used only for the router's cost score until real spend accrues.
_UNIT_COST_MINOR: dict[str, int] = {
    "text_to_image": 15,
    "image_to_image": 15,
    "audio_generation": 4,
    "text_to_video": 120,
    "image_to_video": 120,
    "video_to_video": 140,
}
_ALL_TIERS = frozenset({"preview", "standard", "cinematic"})


def dynamic_capabilities(session: Session) -> dict[str, ProviderCapability]:
    """One `ProviderCapability` per enabled capability of every enabled
    `kind="media"` endpoint, keyed `f"{endpoint_id}:{capability_tag}"`.

    An endpoint offering both `text_to_image` and `audio_generation` yields
    two independent catalog entries — each scored and dispatched on its own,
    because "primary for images" need not mean "primary for audio".
    """
    config = config_service.get_typed(session, "llm_providers", LlmProviderConfig)
    catalog: dict[str, ProviderCapability] = {}
    for endpoint_id, endpoint in config.endpoints.items():
        if not endpoint.enabled or endpoint.kind != "media":
            continue
        for tag, capability in endpoint.capabilities.items():
            if not capability.enabled:
                continue
            catalog_key = f"{endpoint_id}:{tag}"
            catalog[catalog_key] = ProviderCapability(
                name=catalog_key,
                kind=ProviderKind.COMMERCIAL_API,
                operations=frozenset({tag}),
                tiers=_ALL_TIERS,
                quality_prior=_QUALITY_PRIOR,
                typical_latency_ms=_TYPICAL_LATENCY_MS.get(tag, 30_000),
                unit_cost_minor=_UNIT_COST_MINOR.get(tag, 20),
                model_or_workflow=capability.model,
                provider_factory=_factory(
                    endpoint_id=endpoint_id,
                    capability_tag=tag,
                    model=capability.model,
                    base_url=endpoint.base_url,
                    api_key=endpoint.api_key,
                    timeout_ms=endpoint.timeout_ms,
                ),
            )
    return catalog


def _factory(
    *,
    endpoint_id: str,
    capability_tag: str,
    model: str,
    base_url: str,
    api_key: str,
    timeout_ms: int,
) -> Callable[[], GenerationProvider]:
    return lambda: AiHubMixMediaProvider(
        endpoint_id=endpoint_id,
        capability_tag=capability_tag,
        model=model,
        base_url=base_url,
        api_key=api_key,
        timeout_ms=timeout_ms,
    )
