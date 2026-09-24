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

from app.domain.costs import service as costs_service
from app.models.enums import ProviderKind
from app.platform_config import service as config_service
from app.platform_config.schemas import IMPLEMENTED_MEDIA_PROTOCOLS, LlmProviderConfig
from app.providers.aihubmix_media import (
    MINIMAX_H3_MODEL,
    AiHubMixMediaProvider,
    NativeVideoModelProfile,
    native_video_profile,
)
from app.providers.base import GenerationProvider, ProviderCapability
from app.providers.dmxapi_media import (
    DmxApiMediaProvider,
)
from app.providers.dmxapi_media import (
    VideoModelProfile as DmxApiVideoModelProfile,
)
from app.providers.dmxapi_media import (
    music_style_for_model as dmxapi_music_style_for_model,
)
from app.providers.dmxapi_media import (
    video_model_profile as dmxapi_video_profile,
)
from app.providers.fal_media import (
    FalMediaProvider,
)
from app.providers.fal_media import (
    VideoModelProfile as FalVideoModelProfile,
)
from app.providers.fal_media import (
    music_style_for_model as fal_music_style_for_model,
)
from app.providers.fal_media import (
    video_model_profile as fal_video_profile,
)
from app.providers.minimax_v2_media import (
    MinimaxV2MediaProvider,
)
from app.providers.minimax_v2_media import (
    VideoModelProfile as MinimaxV2VideoModelProfile,
)
from app.providers.minimax_v2_media import (
    video_model_profile as minimax_v2_video_profile,
)

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
    # A synchronous chat-style call, not a polled render task, but still
    # well beyond a text-only completion — the model has to watch the whole
    # clip before it can answer.
    "video_analysis": 25_000,
}
# Fallback per-call cost in micro-USD, used only when an operator has not
# configured a price for the endpoint. Setting these to zero instead would be
# worse than a rough guess: an unpriced endpoint would look free and pull
# every selection towards itself. Candidates carrying one of these are marked
# `cost_is_estimated` so the selecting agent knows the number is a prior.
_FALLBACK_UNIT_COST_MICRO_USD: dict[str, int] = {
    "text_to_image": 150_000,
    "image_to_image": 150_000,
    "audio_generation": 40_000,
    "text_to_video": 1_200_000,
    "image_to_video": 1_200_000,
    "video_to_video": 1_400_000,
    "video_analysis": 80_000,
}
_FALLBACK_DEFAULT_MICRO_USD = 200_000
_ALL_TIERS = frozenset({"preview", "standard", "cinematic"})


def dynamic_capabilities(session: Session) -> dict[str, ProviderCapability]:
    """One `ProviderCapability` per enabled capability of every enabled
    `kind="media"` endpoint, keyed `f"{endpoint_id}:{capability_tag}"`.

    An endpoint offering both `text_to_image` and `audio_generation` yields
    two independent catalog entries — each scored and dispatched on its own,
    because "primary for images" need not mean "primary for audio".

    A `kind="general"` endpoint that declares `"video"` in `input_modalities`
    also gets one entry here, tagged `video_analysis` — the only capability a
    general (text + vision) endpoint can derive. It keeps its ordinary role
    in `app/llm/failover.py`'s primary/backup pool too; the two selection
    paths are independent.
    """
    config = config_service.get_typed(session, "llm_providers", LlmProviderConfig)
    catalog: dict[str, ProviderCapability] = {}
    for endpoint_id, endpoint in config.endpoints.items():
        if not endpoint.enabled:
            continue
        if endpoint.kind == "media":
            if endpoint.protocol not in IMPLEMENTED_MEDIA_PROTOCOLS:
                continue
        elif endpoint.kind == "general":
            # A general endpoint has no `protocol` concept — its only
            # possible capability is `video_analysis`, declared purely via
            # `input_modalities` (see `LlmProviderEndpoint.capabilities`).
            if not endpoint.capabilities:
                continue
        else:
            continue
        for tag in endpoint.capabilities:
            catalog_key = f"{endpoint_id}:{tag}"
            is_native_video = tag in {
                "text_to_video",
                "image_to_video",
                "video_to_video",
            }
            # Scoped to protocols with a per-model physical-limits table.
            # `openai` (either provider's OpenAI Videos API track) sends none
            # of these fields at all, even for the same model name, so it
            # must not inherit either native adapter's range constraints.
            video_profile: (
                NativeVideoModelProfile
                | DmxApiVideoModelProfile
                | MinimaxV2VideoModelProfile
                | FalVideoModelProfile
                | None
            ) = None
            if is_native_video and endpoint.protocol == "minimax":
                video_profile = native_video_profile(endpoint.model)
            elif is_native_video and endpoint.protocol == "dmxapi":
                video_profile = dmxapi_video_profile(endpoint.model)
            elif is_native_video and endpoint.protocol == "minimax_v2":
                video_profile = minimax_v2_video_profile(endpoint.model)
            elif is_native_video and endpoint.protocol == "fal":
                video_profile = fal_video_profile(endpoint.model)
            default_resolution = (
                video_profile.default_resolution if video_profile is not None else None
            )
            configured_cost = costs_service.nominal_media_call_cost_micro_usd(
                endpoint.media_pricing,
                capability=tag,
                billing_profile=endpoint.billing_profile,
                default_resolution=default_resolution,
            )
            catalog[catalog_key] = ProviderCapability(
                name=catalog_key,
                kind=ProviderKind.COMMERCIAL_API,
                operations=frozenset({tag}),
                tiers=_ALL_TIERS,
                quality_prior=_QUALITY_PRIOR,
                typical_latency_ms=_TYPICAL_LATENCY_MS.get(tag, 30_000),
                unit_cost_micro_usd=configured_cost
                or _FALLBACK_UNIT_COST_MICRO_USD.get(tag, _FALLBACK_DEFAULT_MICRO_USD),
                cost_is_estimated=not configured_cost,
                pricing=endpoint.media_pricing,
                billing_profile=endpoint.billing_profile,
                model_or_workflow=endpoint.model,
                min_duration_seconds=(
                    video_profile.min_duration_seconds if video_profile is not None else None
                ),
                max_duration_seconds=(
                    video_profile.max_duration_seconds if video_profile is not None else None
                ),
                aspect_ratios=video_profile.aspect_ratios if video_profile is not None else None,
                resolutions=video_profile.resolutions if video_profile is not None else None,
                default_resolution=default_resolution,
                # `frame_images` (first/last-frame) is an H3-only concept on
                # AiHubMix's native track — any other profiled native-video
                # model there (e.g. wan2.7-videoedit) only ever advertises
                # `input_references`, so a `frame_images` request gets
                # hard-filtered away from it at routing time instead of
                # failing later as a schema violation on the provider's
                # side. DMXAPI's own per-model `reference_modes` already
                # encodes this per model (empty for `MiniMax-H3-
                # video_regeneration`, which takes neither shape — its one
                # required `base_video` reference is enforced by the
                # provider, not this hard filter, so it is left
                # unrestricted here rather than mis-modelled as one of the
                # two AiHubMix-shaped tags). A model with no profile at all
                # stays unrestricted, same as before this table existed.
                reference_modes=_reference_modes_for(
                    endpoint.protocol, endpoint.model, video_profile
                ),
                generation_kind=endpoint.generation_kind,
                music_styles=_music_styles_for(endpoint.protocol, endpoint.model, tag),
                accepts_video_reference=_accepts_video_reference(
                    endpoint.protocol, endpoint.model, video_profile
                ),
                provider_factory=_factory(
                    endpoint_id=endpoint_id,
                    capability_tag=tag,
                    model=endpoint.model,
                    base_url=endpoint.base_url,
                    api_key=endpoint.api_key,
                    timeout_ms=endpoint.timeout_ms,
                    protocol=endpoint.protocol or "minimax",
                ),
            )
    return catalog


def _reference_modes_for(
    protocol: str | None,
    model: str,
    video_profile: NativeVideoModelProfile
    | DmxApiVideoModelProfile
    | MinimaxV2VideoModelProfile
    | FalVideoModelProfile
    | None,
) -> frozenset[str] | None:
    if video_profile is None:
        return None
    if protocol == "minimax":
        return (
            frozenset({"input_references", "frame_images"})
            if model.strip().lower() == MINIMAX_H3_MODEL
            else frozenset({"input_references"})
        )
    if protocol in {"dmxapi", "minimax_v2", "fal"}:
        modes = getattr(video_profile, "reference_modes", None)
        return modes or None
    return None


def _accepts_video_reference(
    protocol: str | None,
    model: str,
    video_profile: NativeVideoModelProfile
    | DmxApiVideoModelProfile
    | MinimaxV2VideoModelProfile
    | FalVideoModelProfile
    | None,
) -> bool:
    """True only for a profiled model whose `input_references` shape carries
    video items to the vendor as references: DMXAPI/MiniMax v2/fal H3,
    Seedance 2.5 and wan3.0 (`reference_video` role / `reference_video_urls`),
    and AiHubMix's native `minimax-h3` (`video_url` input references). A
    model that *requires* a video (H3 regeneration) is an edit, not a
    guided generation, and an unprofiled model is unknown — both stay out."""
    if video_profile is None:
        return False
    if protocol == "minimax":
        return model.strip().lower() == MINIMAX_H3_MODEL
    if protocol in {"dmxapi", "minimax_v2", "fal"}:
        if getattr(video_profile, "requires_video_reference", False):
            return False
        modes = getattr(video_profile, "reference_modes", None) or frozenset()
        return "input_references" in modes
    return False


def _music_styles_for(protocol: str | None, model: str, tag: str) -> frozenset[str] | None:
    """Scoped to `music_generation` only — see `ProviderCapability.
    music_styles`'s own docstring for why every other capability leaves
    this `None` (unrestricted)."""
    if tag != "music_generation":
        return None
    if protocol == "dmxapi":
        return dmxapi_music_style_for_model(model)
    if protocol == "fal":
        return fal_music_style_for_model(model)
    return None


def _factory(
    *,
    endpoint_id: str,
    capability_tag: str,
    model: str,
    base_url: str,
    api_key: str,
    timeout_ms: int,
    protocol: str,
) -> Callable[[], GenerationProvider]:
    if protocol == "dmxapi":
        return lambda: DmxApiMediaProvider(
            endpoint_id=endpoint_id,
            capability_tag=capability_tag,
            model=model,
            base_url=base_url,
            api_key=api_key,
            timeout_ms=timeout_ms,
        )
    if protocol == "minimax_v2":
        return lambda: MinimaxV2MediaProvider(
            endpoint_id=endpoint_id,
            capability_tag=capability_tag,
            model=model,
            base_url=base_url,
            api_key=api_key,
            timeout_ms=timeout_ms,
        )
    if protocol == "fal":
        return lambda: FalMediaProvider(
            endpoint_id=endpoint_id,
            capability_tag=capability_tag,
            model=model,
            base_url=base_url,
            api_key=api_key,
            timeout_ms=timeout_ms,
        )
    return lambda: AiHubMixMediaProvider(
        endpoint_id=endpoint_id,
        capability_tag=capability_tag,
        model=model,
        base_url=base_url,
        api_key=api_key,
        timeout_ms=timeout_ms,
        protocol=protocol,
    )
