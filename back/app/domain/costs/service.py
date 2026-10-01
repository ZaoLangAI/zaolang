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
    MusicPricing,
    TokenPricing,
    TokenVideoPricing,
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
    cached_prompt_tokens: int = 0,
) -> int:
    """What one chat completion cost, from its token usage.

    Returns 0 when the endpoint has no declared price — "we do not know",
    which the statistics module reports as unpriced rather than as free.

    `cached_prompt_tokens` is the portion of `prompt_tokens` that hit a
    prompt cache and bills at `TokenPricing.cached_input_per_million_
    micro_usd` instead of the regular input rate — a subset of
    `prompt_tokens`, not additional to it. No caller passes a non-zero value
    today (the gateway client does not yet parse a cache-hit count out of
    the upstream response), so every existing call site's arithmetic is
    unchanged; this parameter exists so the rate an operator declares (e.g.
    GLM-5.3-Flash's cached-input price) is already correct the day that
    parsing lands.
    """
    if pricing is None or not pricing.is_declared:
        return 0
    prompt = max(prompt_tokens or 0, 0)
    cached = min(max(cached_prompt_tokens, 0), prompt)
    regular = prompt - cached
    return _ceil_div(
        regular * pricing.input_per_million_micro_usd
        + cached * pricing.cached_input_per_million_micro_usd
        + max(completion_tokens or 0, 0) * pricing.output_per_million_micro_usd,
        TOKENS_PER_PRICING_UNIT,
    )


def image_call_cost_micro_usd(
    pricing: ImagePricing | None,
    *,
    input_images: int = 0,
    generated_images: int = 1,
    tier: str = "",
) -> int:
    """Images are billed on both sides — an edit that consumes three
    references and returns one image pays for four.

    `tier` selects a size-tiered generation rate (Doubao Seedream's "1K"/
    "2K") from `generation_per_image_by_tier_micro_usd` when the vendor
    quotes one; an empty tier or one the pricing does not declare falls back
    to the flat `generation_per_image_micro_usd`, so a model that only ever
    had one rate keeps costing exactly what it did before this parameter
    existed. `reference_image_free_count` reduces the billable input-image
    count first (0 — the default — bills every input image, unchanged).
    """
    if pricing is None or not pricing.is_declared:
        return 0
    billable_inputs = max(input_images - pricing.reference_image_free_count, 0)
    per_image = pricing.generation_per_image_by_tier_micro_usd.get(tier) if tier else None
    if per_image is None:
        per_image = pricing.generation_per_image_micro_usd
    return billable_inputs * pricing.input_per_image_micro_usd + max(generated_images, 0) * (
        per_image
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


def music_call_cost_micro_usd(pricing: MusicPricing | None) -> int:
    """Flat per-clip price — see `MusicPricing`'s own docstring for why a
    music/SFX call never bills by prompt length or rendered duration, even
    for a vendor (ElevenLabs Sound Effects V2) that itself bills per
    second."""
    if pricing is None or not pricing.is_declared:
        return 0
    return pricing.per_request_micro_usd


# Doubao Seedance's own published formula bills *tokens*, not seconds:
# tokens = (input video seconds + output seconds) x width x height x fps / 1024.
# Pixel area is looked up by resolution tier rather than an exact per-request
# width/height (`GenerationRequest` carries a resolution label like "720p",
# not pixel dimensions), so this is a representative area for that tier —
# an estimate, same spirit as every other "nominal" figure in this module,
# not a promise that a 16:9 and a 9:16 request at the same tier cost
# identically to the decimal.
SEEDANCE_TOKEN_FPS = 24
SEEDANCE_TOKEN_DIVISOR = 1024
_SEEDANCE_RESOLUTION_PIXELS: dict[str, int] = {
    "480p": 864 * 480,
    "480P": 864 * 480,
    "720p": 1280 * 720,
    "720P": 1280 * 720,
    "1080p": 1920 * 1080,
    "1080P": 1920 * 1080,
}
_SEEDANCE_DEFAULT_RESOLUTION = "720p"

# `LlmProviderEndpoint.billing_profile` value that routes a media endpoint
# through `seedance_video_cost_micro_usd` instead of the default per-second
# `video_call_cost_micro_usd` — mirrors `app.providers.model_catalog`'s
# `billing_profile` id for the Seedance catalogue entries so the two never
# drift apart under different spellings.
SEEDANCE_TOKENS_BILLING_PROFILE = "seedance_tokens"


def seedance_video_tokens(
    *, resolution: str, output_seconds: int, input_video_seconds: int = 0
) -> int:
    """The billable token count for one Seedance-style call.

    Rounds up like every other unit conversion here: a fractional token at
    the boundary must not vanish into an under-reported spend.
    """
    pixels = _SEEDANCE_RESOLUTION_PIXELS.get(
        resolution, _SEEDANCE_RESOLUTION_PIXELS[_SEEDANCE_DEFAULT_RESOLUTION]
    )
    total_seconds = max(output_seconds, 0) + max(input_video_seconds, 0)
    return _ceil_div(total_seconds * pixels * SEEDANCE_TOKEN_FPS, SEEDANCE_TOKEN_DIVISOR)


def seedance_video_cost_micro_usd(
    pricing: TokenVideoPricing | None,
    *,
    resolution: str,
    output_seconds: int,
    input_video_seconds: int = 0,
    has_video_reference: bool = False,
) -> int:
    """Prices one Seedance-style call: the token formula above, times
    whichever of the two declared rates the request qualifies for.

    `input_video_seconds` folds in only what the caller can supply — today's
    callers do not yet track an attached reference clip's own duration, so
    it defaults to 0 (the request's own output seconds still price
    correctly; only the video-reference share of the token count is
    understated until that duration is threaded through). `has_video_
    reference` is real and derived from the request today (see
    `generation_attempt_cost_micro_usd`), so the *rate* is always correct
    even when the *duration* term is not.
    """
    if pricing is None or not pricing.is_declared:
        return 0
    tokens = seedance_video_tokens(
        resolution=resolution,
        output_seconds=output_seconds,
        input_video_seconds=input_video_seconds,
    )
    rate = (
        pricing.per_million_tokens_with_video_ref_micro_usd
        if has_video_reference
        else pricing.per_million_tokens_micro_usd
    )
    return _ceil_div(tokens * rate, TOKENS_PER_PRICING_UNIT)


def media_call_cost_micro_usd(
    pricing: MediaPricing | None,
    *,
    capability: str,
    billing_profile: str | None = None,
    resolution: str = "",
    duration_seconds: int = 0,
    input_material_seconds: int = 0,
    prompt_characters: int = 0,
    input_images: int = 0,
    generated_images: int = 1,
    reference_images: int = 0,
    image_tier: str = "",
    has_video_reference: bool = False,
) -> int:
    """Dispatches to the section that prices `capability`.

    Callers pass everything they know about the request and let this decide
    what applies, so a worker recording an attempt does not have to carry a
    branch per media type. `billing_profile` picks the *shape*, not just the
    section: a `"seedance_tokens"` endpoint bills `pricing.token_video`'s
    formula instead of `pricing.video`'s per-second rate even though both
    price the same `text_to_video`/`image_to_video`/`video_to_video`
    capabilities.
    """
    if pricing is None:
        return 0
    if billing_profile == SEEDANCE_TOKENS_BILLING_PROFILE and pricing.token_video is not None:
        return seedance_video_cost_micro_usd(
            pricing.token_video,
            resolution=resolution,
            output_seconds=duration_seconds,
            input_video_seconds=input_material_seconds,
            has_video_reference=has_video_reference,
        )
    section = pricing_section_for(capability)
    if section == "image":
        return image_call_cost_micro_usd(
            pricing.image,
            input_images=input_images,
            generated_images=generated_images,
            tier=image_tier,
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
    if section == "music":
        return music_call_cost_micro_usd(pricing.music)
    return 0


# A representative call, used to price a capability before a specific request
# exists — what the router shows when comparing providers in the abstract.
NOMINAL_VIDEO_SECONDS = 6
NOMINAL_AUDIO_CHARACTERS = 1_000
NOMINAL_VIDEO_RESOLUTION = "2K"


def generation_attempt_cost_micro_usd(
    pricing: MediaPricing | None,
    *,
    capability: str,
    request: GenerationRequest,
    billing_profile: str | None = None,
    default_resolution: str | None = None,
) -> int:
    """Prices one settled provider attempt from the request that produced it.

    The single place workers agree on what an attempt cost, so the number a
    generation records and the number a poll records cannot diverge.

    `references` covers both sides of the ledger: for an image edit they are
    the input images being billed, for a video they are the reference frames
    beyond the free allowance. `has_video_reference` (whether any attached
    reference is itself a video) is a real signal read straight off the
    request — unlike the referenced clip's own duration, which nothing
    upstream of this function tracks yet (see `seedance_video_cost_micro_usd`).

    `default_resolution` is the model's own fallback when the request itself
    leaves `resolution` unset (see `_requested_resolution`) — pass `capability
    .default_resolution` from the `ProviderCapability` that served this call.
    """
    reference_count = len(request.references) + len(request.reference_object_keys)
    has_video_reference = any(ref.media_type == "video" for ref in request.references)
    return media_call_cost_micro_usd(
        pricing,
        capability=capability,
        billing_profile=billing_profile,
        resolution=_requested_resolution(request, default_resolution),
        duration_seconds=request.duration_seconds,
        prompt_characters=len(request.prompt or ""),
        input_images=reference_count,
        reference_images=reference_count,
        has_video_reference=has_video_reference,
    )


def _requested_resolution(request: GenerationRequest, default_resolution: str | None = None) -> str:
    """`GenerationRequest.resolution` is the field the workflow node actually
    populates from the job's `video_options.resolution` (see
    `app.workflows.nodes`); `request.extra` is a distinct, unrelated JSON
    blob that has never carried a `video_options` key, so reading it here
    used to fall through to the nominal resolution for every real request —
    silently pricing every video at `NOMINAL_VIDEO_RESOLUTION` regardless of
    what was actually requested.

    By the time a settled `request` reaches this function, `nodes.py` has
    already turned the client's tier *ceiling* (`VideoGenerationOptions
    .resolution` — see `app.providers.base.adapt_resolution_tier`) into
    the specific vendor spelling the routed model's own profile declares, so
    `request.resolution` is populated for every native video model, not just
    MiniMax H3. It is still `None` on a video remix (the client omits
    `resolution` entirely so the router does not default-filter a cheaper
    edit model) — that's when `default_resolution` (the model's own declared
    default, `NativeVideoModelProfile`/`VideoModelProfile.default_resolution`)
    matters: falling back straight to the fixed `NOMINAL_VIDEO_RESOLUTION`
    instead prices the call at a resolution the model never actually
    rendered at, so whatever the operator configured for the model's *real*
    default resolution is never looked up. `default_resolution` is `None`
    for a model with no declared profile (e.g. a hand-typed custom
    endpoint), which still falls through to the fixed nominal exactly as
    before.
    """
    return request.resolution or default_resolution or NOMINAL_VIDEO_RESOLUTION


def estimate_media_request_cost_micro_usd(
    pricing: MediaPricing | None,
    *,
    capability: str,
    params: Mapping[str, Any],
    billing_profile: str | None = None,
    default_resolution: str | None = None,
) -> int:
    """What this specific request would cost, from the job's own parameters.

    Falls back to the nominal figures for anything the request does not
    specify, so a comparison between two candidates never mixes a fully
    detailed estimate against a blank one. Called before submission (the
    router comparing candidates), so there is no per-reference media type
    to inspect yet — `video_options.reference_mode` only distinguishes
    "regular references" from "first/last frame", not "image reference" from
    "video reference" (see `VideoGenerationOptions`), so `has_video_
    reference` stays `False` here rather than guessing: for a Seedance-style
    two-rate endpoint that means the estimate uses the *more expensive* of
    the two rates, which is the safer direction for a pre-call estimate to
    be wrong in. `default_resolution` is the same per-model fallback
    `generation_attempt_cost_micro_usd` uses — see `_requested_resolution`.

    `params["video_options"]["resolution"]`, when present, is used as a
    literal pricing-table key — its only caller (`router.route()`) has
    already adapted the client's tier ceiling into this specific candidate's
    own vendor spelling (`app.providers.base.adapt_resolution_tier`)
    before calling this, so a raw unmatched tier token never reaches this lookup.
    """
    video_options = params.get("video_options")
    resolution = default_resolution or NOMINAL_VIDEO_RESOLUTION
    if isinstance(video_options, Mapping) and video_options.get("resolution"):
        resolution = str(video_options["resolution"])
    duration = int(params.get("duration_seconds") or 0) or NOMINAL_VIDEO_SECONDS
    prompt_characters = len(str(params.get("prompt") or "")) or NOMINAL_AUDIO_CHARACTERS
    reference_images = int(params.get("reference_image_count") or 0)
    # A 白膜 motion guide is rendered at exactly the clip's own length, so
    # here — unlike an arbitrary attached clip — the reference video's
    # duration *is* known, and per-second/token models bill it too.
    motion_guide = (
        isinstance(video_options, Mapping)
        and video_options.get("reference_video_role") == "motion_guide"
    )
    return media_call_cost_micro_usd(
        pricing,
        capability=capability,
        billing_profile=billing_profile,
        resolution=resolution,
        duration_seconds=duration,
        input_material_seconds=duration if motion_guide else 0,
        prompt_characters=prompt_characters,
        input_images=reference_images,
        reference_images=reference_images,
        has_video_reference=motion_guide,
    )


def nominal_media_call_cost_micro_usd(
    pricing: MediaPricing | None,
    *,
    capability: str,
    billing_profile: str | None = None,
    default_resolution: str | None = None,
) -> int:
    """Roughly what one call to this capability costs, ignoring the request.

    The router needs a single comparable number per candidate before it knows
    what is being asked for. A six-second clip at the model's own default
    resolution (not a fixed nominal one — see `_requested_resolution`) and a
    thousand characters of speech are stand-ins, not predictions —
    `media_call_cost_micro_usd` with the real request is what gets recorded.
    """
    return media_call_cost_micro_usd(
        pricing,
        capability=capability,
        billing_profile=billing_profile,
        resolution=default_resolution or NOMINAL_VIDEO_RESOLUTION,
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
