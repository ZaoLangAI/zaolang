"""Turns configured list prices into what one call actually cost us.

Every function here is pure: prices in, integer micro-USD out, no session and
no I/O. That matters because the same arithmetic runs in two very different
places — after a call, to snapshot what we spent, and before one, to estimate
what a candidate provider *would* spend. Sharing the code is the only way an
estimate and the eventual charge stay comparable.

Micro-USD (1e-6 USD) integers throughout, never floats: a rate like $0.00286
per image is exactly 2_860 here, whereas float arithmetic over a month of
traffic drifts. Rounding, where a rate does not divide evenly, is *up* — an
under-reported spend is the more dangerous error for the people reading these
numbers to decide whether a model is affordable.

This is money we pay a vendor. It is not the credit price a user pays us
(`PricingConfig` / `app.domain.credits`), and the two never convert into one
another — a model getting cheaper does not make a generation cheaper to buy.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from app.platform_config.schemas import (
    AudioPricing,
    ImagePricing,
    MediaPricing,
    TokenPricing,
    VideoAnalysisPricing,
    VideoPricing,
    pricing_section_for,
)

if TYPE_CHECKING:
    # Annotation only. A domain module must not depend on the provider layer
    # at runtime — the provider layer already depends on this one.
    from app.providers.base import GenerationRequest

TOKENS_PER_PRICING_UNIT = 1_000_000
CHARACTERS_PER_PRICING_UNIT = 10_000


def llm_call_cost_micro_usd(
    pricing: TokenPricing | None,
    *,
    prompt_tokens: int | None,
    completion_tokens: int | None,
) -> int:
    """What one chat completion cost, from its token usage.

    Returns 0 when the endpoint has no declared price — "we do not know",
    which the statistics module reports as unpriced rather than as free.
    """
    if pricing is None or not pricing.is_declared:
        return 0
    return _ceil_div(
        max(prompt_tokens or 0, 0) * pricing.input_per_million_micro_usd
        + max(completion_tokens or 0, 0) * pricing.output_per_million_micro_usd,
        TOKENS_PER_PRICING_UNIT,
    )


def image_call_cost_micro_usd(
    pricing: ImagePricing | None, *, input_images: int = 0, generated_images: int = 1
) -> int:
    """Images are billed on both sides — an edit that consumes three
    references and returns one image pays for four."""
    if pricing is None or not pricing.is_declared:
        return 0
    return (
        max(input_images, 0) * pricing.input_per_image_micro_usd
        + max(generated_images, 0) * pricing.generation_per_image_micro_usd
    )


def audio_call_cost_micro_usd(pricing: AudioPricing | None, *, characters: int) -> int:
    """Speech synthesis bills the text going in, not the audio coming out."""
    if pricing is None or not pricing.is_declared:
        return 0
    return _ceil_div(
        max(characters, 0) * pricing.per_10k_characters_micro_usd, CHARACTERS_PER_PRICING_UNIT
    )


def video_call_cost_micro_usd(
    pricing: VideoPricing | None,
    *,
    resolution: str,
    duration_seconds: int,
    input_material_seconds: int = 0,
    reference_images: int = 0,
) -> int:
    """Generated seconds, supplied material seconds, and reference images.

    A resolution the operator never priced contributes nothing rather than
    borrowing another tier's rate: silently billing 2K at the 768P rate would
    make a whole resolution look artificially cheap in the cost report.
    """
    if pricing is None or not pricing.is_declared:
        return 0
    total = max(duration_seconds, 0) * pricing.generation_per_second_micro_usd.get(resolution, 0)
    total += max(input_material_seconds, 0) * pricing.input_material_per_second_micro_usd.get(
        resolution, 0
    )
    billable_images = max(reference_images - pricing.reference_image_free_count, 0)
    return total + billable_images * pricing.extra_reference_image_micro_usd


def video_analysis_call_cost_micro_usd(pricing: VideoAnalysisPricing | None) -> int:
    """Flat per-call price — a video-understanding request has no per-second
    or per-image dimension the way generation/synthesis calls do."""
    if pricing is None or not pricing.is_declared:
        return 0
    return pricing.per_request_micro_usd


def media_call_cost_micro_usd(
    pricing: MediaPricing | None,
    *,
    capability: str,
    resolution: str = "",
    duration_seconds: int = 0,
    input_material_seconds: int = 0,
    prompt_characters: int = 0,
    input_images: int = 0,
    generated_images: int = 1,
    reference_images: int = 0,
) -> int:
    """Dispatches to the section that prices `capability`.

    Callers pass everything they know about the request and let this decide
    what applies, so a worker recording an attempt does not have to carry a
    branch per media type.
    """
    if pricing is None:
        return 0
    section = pricing_section_for(capability)
    if section == "image":
        return image_call_cost_micro_usd(
            pricing.image, input_images=input_images, generated_images=generated_images
        )
    if section == "audio":
        return audio_call_cost_micro_usd(pricing.audio, characters=prompt_characters)
    if section == "video":
        return video_call_cost_micro_usd(
            pricing.video,
            resolution=resolution,
            duration_seconds=duration_seconds,
            input_material_seconds=input_material_seconds,
            reference_images=reference_images,
        )
    if section == "video_analysis":
        return video_analysis_call_cost_micro_usd(pricing.video_analysis)
    return 0


# A representative call, used to price a capability before a specific request
# exists — what the router shows when comparing providers in the abstract.
NOMINAL_VIDEO_SECONDS = 6
NOMINAL_AUDIO_CHARACTERS = 1_000
NOMINAL_VIDEO_RESOLUTION = "2K"


def generation_attempt_cost_micro_usd(
    pricing: MediaPricing | None, *, capability: str, request: GenerationRequest
) -> int:
    """Prices one settled provider attempt from the request that produced it.

    The single place workers agree on what an attempt cost, so the number a
    generation records and the number a poll records cannot diverge.

    `references` covers both sides of the ledger: for an image edit they are
    the input images being billed, for a video they are the reference frames
    beyond the free allowance.
    """
    reference_count = len(request.references) + len(request.reference_object_keys)
    return media_call_cost_micro_usd(
        pricing,
        capability=capability,
        resolution=_requested_resolution(request),
        duration_seconds=request.duration_seconds,
        prompt_characters=len(request.prompt or ""),
        input_images=reference_count,
        reference_images=reference_count,
    )


def _requested_resolution(request: GenerationRequest) -> str:
    options = request.extra.get("video_options")
    if isinstance(options, Mapping):
        return str(options.get("resolution") or NOMINAL_VIDEO_RESOLUTION)
    return NOMINAL_VIDEO_RESOLUTION


def estimate_media_request_cost_micro_usd(
    pricing: MediaPricing | None, *, capability: str, params: Mapping[str, Any]
) -> int:
    """What this specific request would cost, from the job's own parameters.

    Falls back to the nominal figures for anything the request does not
    specify, so a comparison between two candidates never mixes a fully
    detailed estimate against a blank one.
    """
    video_options = params.get("video_options")
    resolution = NOMINAL_VIDEO_RESOLUTION
    if isinstance(video_options, Mapping):
        resolution = str(video_options.get("resolution") or NOMINAL_VIDEO_RESOLUTION)
    duration = int(params.get("duration_seconds") or 0) or NOMINAL_VIDEO_SECONDS
    prompt_characters = len(str(params.get("prompt") or "")) or NOMINAL_AUDIO_CHARACTERS
    reference_images = int(params.get("reference_image_count") or 0)
    return media_call_cost_micro_usd(
        pricing,
        capability=capability,
        resolution=resolution,
        duration_seconds=duration,
        prompt_characters=prompt_characters,
        input_images=reference_images,
        reference_images=reference_images,
    )


def nominal_media_call_cost_micro_usd(pricing: MediaPricing | None, *, capability: str) -> int:
    """Roughly what one call to this capability costs, ignoring the request.

    The router needs a single comparable number per candidate before it knows
    what is being asked for. A six-second 2K clip and a thousand characters of
    speech are stand-ins, not predictions — `media_call_cost_micro_usd` with
    the real request is what gets recorded.
    """
    return media_call_cost_micro_usd(
        pricing,
        capability=capability,
        resolution=NOMINAL_VIDEO_RESOLUTION,
        duration_seconds=NOMINAL_VIDEO_SECONDS,
        prompt_characters=NOMINAL_AUDIO_CHARACTERS,
    )


def _ceil_div(numerator: int, denominator: int) -> int:
    """Rounds a partial unit up, staying in integers.

    See the module docstring on why up. Float division would be close enough
    for one call and wrong by the time a month of them is summed.
    """
    if numerator <= 0:
        return 0
    return -(-numerator // denominator)
