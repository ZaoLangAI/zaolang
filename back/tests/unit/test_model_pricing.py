"""What a configured list price turns into when a call is billed.

Every rate here is one an operator actually typed into the console, kept as
the vendor quoted it in the test name so a change to the arithmetic has to
argue with a real invoice rather than with a made-up number.
"""

from __future__ import annotations

import pytest

from app.domain.costs import service as costs
from app.platform_config.schemas import (
    AudioPricing,
    ImagePricing,
    LlmProviderEndpoint,
    MediaPricing,
    TokenPricing,
    TokenVideoPricing,
    VideoPricing,
)
from app.providers.base import GenerationRequest, ProviderReference

# The prices as quoted, converted once here so each test reads as the vendor's
# own figure rather than as a six-digit integer.
INPUT_TOKENS_PER_M = 60_000  # $0.060 / M tokens
OUTPUT_TOKENS_PER_M = 220_000  # $0.220 / M tokens
IMAGE_INPUT = 2_860  # $0.00286 / image
IMAGE_GENERATION = 25_350  # $0.02535 / image
AUDIO_PER_10K = 141_000  # $0.141 / 10K characters
VIDEO_2K_PER_SECOND = 123_970  # $0.12397 / s
VIDEO_768P_PER_SECOND = 77_440  # $0.07744 / s
EXTRA_REFERENCE_IMAGE = 28_200  # $0.0282 / image beyond the fifth


def _token_pricing() -> TokenPricing:
    return TokenPricing(
        input_per_million_micro_usd=INPUT_TOKENS_PER_M,
        output_per_million_micro_usd=OUTPUT_TOKENS_PER_M,
    )


def _video_pricing() -> VideoPricing:
    return VideoPricing(
        generation_per_second_micro_usd={
            "2K": VIDEO_2K_PER_SECOND,
            "768P": VIDEO_768P_PER_SECOND,
        },
        input_material_per_second_micro_usd={
            "2K": VIDEO_2K_PER_SECOND,
            "768P": VIDEO_768P_PER_SECOND,
        },
        reference_image_free_count=5,
        extra_reference_image_micro_usd=EXTRA_REFERENCE_IMAGE,
    )


def test_a_million_tokens_each_way_costs_exactly_the_quoted_rates() -> None:
    cost = costs.llm_call_cost_micro_usd(
        _token_pricing(), prompt_tokens=1_000_000, completion_tokens=1_000_000
    )

    assert cost == INPUT_TOKENS_PER_M + OUTPUT_TOKENS_PER_M


def test_a_realistic_token_count_rounds_up_rather_than_down() -> None:
    # 1_500 * 60_000 / 1e6 is 90 exactly; 700 * 220_000 / 1e6 is 154 exactly,
    # so the sum lands on 244 with no rounding. One extra prompt token is what
    # forces the fraction, and it must round up, not vanish.
    exact = costs.llm_call_cost_micro_usd(
        _token_pricing(), prompt_tokens=1_500, completion_tokens=700
    )
    assert exact == 244

    fractional = costs.llm_call_cost_micro_usd(
        _token_pricing(), prompt_tokens=1_501, completion_tokens=700
    )
    assert fractional == 245


def test_an_undeclared_token_price_costs_nothing_rather_than_guessing() -> None:
    assert (
        costs.llm_call_cost_micro_usd(
            TokenPricing(), prompt_tokens=1_000_000, completion_tokens=1_000_000
        )
        == 0
    )
    assert costs.llm_call_cost_micro_usd(None, prompt_tokens=1_000_000, completion_tokens=0) == 0


def test_a_cached_prompt_hit_bills_at_the_cached_rate_not_the_regular_one() -> None:
    # GLM-5.3-Flash-shaped: cached input is well below the regular rate.
    cached_rate = 31_945  # 0.23 元/M
    pricing = TokenPricing(
        input_per_million_micro_usd=INPUT_TOKENS_PER_M,
        output_per_million_micro_usd=OUTPUT_TOKENS_PER_M,
        cached_input_per_million_micro_usd=cached_rate,
    )

    # 1M prompt tokens, all of it a cache hit: bills at the cached rate only.
    all_cached = costs.llm_call_cost_micro_usd(
        pricing, prompt_tokens=1_000_000, completion_tokens=0, cached_prompt_tokens=1_000_000
    )
    assert all_cached == cached_rate

    # Half a cache hit: the cached half at the cached rate, the rest at the
    # regular rate — never double-billed, never billed as additional tokens.
    half_cached = costs.llm_call_cost_micro_usd(
        pricing, prompt_tokens=1_000_000, completion_tokens=0, cached_prompt_tokens=500_000
    )
    expected = costs._ceil_div(500_000 * INPUT_TOKENS_PER_M + 500_000 * cached_rate, 1_000_000)
    assert half_cached == expected


def test_a_cached_count_larger_than_the_prompt_is_clamped_not_double_counted() -> None:
    pricing = TokenPricing(
        input_per_million_micro_usd=INPUT_TOKENS_PER_M,
        cached_input_per_million_micro_usd=1,
    )
    cost = costs.llm_call_cost_micro_usd(
        pricing, prompt_tokens=100, completion_tokens=0, cached_prompt_tokens=10_000
    )
    # The entire prompt at the cached rate — not negative regular tokens.
    assert cost == costs._ceil_div(100 * 1, costs.TOKENS_PER_PRICING_UNIT)


def test_every_existing_llm_caller_is_unaffected_by_the_new_cache_parameter() -> None:
    """No caller passes `cached_prompt_tokens` yet — the default must
    reproduce the exact pre-existing arithmetic."""
    with_default = costs.llm_call_cost_micro_usd(
        _token_pricing(), prompt_tokens=1_500, completion_tokens=700
    )
    explicit_zero = costs.llm_call_cost_micro_usd(
        _token_pricing(), prompt_tokens=1_500, completion_tokens=700, cached_prompt_tokens=0
    )
    assert with_default == explicit_zero == 244


def test_an_image_edit_pays_for_what_it_consumed_and_what_it_produced() -> None:
    pricing = ImagePricing(
        input_per_image_micro_usd=IMAGE_INPUT,
        generation_per_image_micro_usd=IMAGE_GENERATION,
    )

    cost = costs.image_call_cost_micro_usd(pricing, input_images=3, generated_images=1)

    assert cost == 3 * IMAGE_INPUT + IMAGE_GENERATION


def test_a_tiered_image_price_wins_over_the_flat_rate_for_its_own_tier() -> None:
    # Doubao Seedream-shaped: 1K and 2K generation cost differently, and a
    # tier this endpoint never declared falls back to the flat rate.
    tier_1k = 41_667  # 0.30 元/张
    tier_2k = 83_334  # 0.60 元/张
    pricing = ImagePricing(
        generation_per_image_micro_usd=IMAGE_GENERATION,
        generation_per_image_by_tier_micro_usd={"1K": tier_1k, "2K": tier_2k},
    )

    assert costs.image_call_cost_micro_usd(pricing, tier="1K") == tier_1k
    assert costs.image_call_cost_micro_usd(pricing, tier="2K") == tier_2k
    # "4K" was never declared for this endpoint — falls back to the flat rate
    # rather than reading as free or as one of the declared tiers.
    assert costs.image_call_cost_micro_usd(pricing, tier="4K") == IMAGE_GENERATION
    # No tier requested at all behaves exactly as before this parameter
    # existed.
    assert costs.image_call_cost_micro_usd(pricing) == IMAGE_GENERATION


def test_a_free_reference_image_count_reduces_billable_inputs_first() -> None:
    # Seedream-shaped: the first reference image is free, the second bills.
    pricing = ImagePricing(
        input_per_image_micro_usd=IMAGE_INPUT,
        generation_per_image_micro_usd=IMAGE_GENERATION,
        reference_image_free_count=1,
    )

    one_input = costs.image_call_cost_micro_usd(pricing, input_images=1)
    two_inputs = costs.image_call_cost_micro_usd(pricing, input_images=2)

    assert one_input == IMAGE_GENERATION
    assert two_inputs == one_input + IMAGE_INPUT


def test_the_default_free_count_of_zero_bills_every_input_image_unchanged() -> None:
    """No caller passed `reference_image_free_count` before this field
    existed — the default of 0 must reproduce that exact arithmetic."""
    pricing = ImagePricing(
        input_per_image_micro_usd=IMAGE_INPUT,
        generation_per_image_micro_usd=IMAGE_GENERATION,
    )

    assert (
        costs.image_call_cost_micro_usd(pricing, input_images=3, generated_images=1)
        == 3 * IMAGE_INPUT + IMAGE_GENERATION
    )


def test_ten_thousand_characters_of_speech_costs_the_quoted_rate() -> None:
    pricing = AudioPricing(per_10k_characters_micro_usd=AUDIO_PER_10K)

    assert costs.audio_call_cost_micro_usd(pricing, characters=10_000) == AUDIO_PER_10K
    # A single character is billed as a fraction rounded up, never as free.
    assert costs.audio_call_cost_micro_usd(pricing, characters=1) == 15


@pytest.mark.parametrize(
    ("resolution", "per_second"),
    [("2K", VIDEO_2K_PER_SECOND), ("768P", VIDEO_768P_PER_SECOND)],
)
def test_each_video_resolution_bills_at_its_own_tier(resolution: str, per_second: int) -> None:
    cost = costs.video_call_cost_micro_usd(
        _video_pricing(), resolution=resolution, duration_seconds=6
    )

    assert cost == 6 * per_second


def test_input_material_is_billed_on_top_of_the_generated_seconds() -> None:
    cost = costs.video_call_cost_micro_usd(
        _video_pricing(), resolution="2K", duration_seconds=6, input_material_seconds=4
    )

    assert cost == 10 * VIDEO_2K_PER_SECOND


def test_the_first_five_reference_images_are_free_and_the_sixth_is_not() -> None:
    five = costs.video_call_cost_micro_usd(
        _video_pricing(), resolution="2K", duration_seconds=6, reference_images=5
    )
    seven = costs.video_call_cost_micro_usd(
        _video_pricing(), resolution="2K", duration_seconds=6, reference_images=7
    )

    assert five == 6 * VIDEO_2K_PER_SECOND
    assert seven == five + 2 * EXTRA_REFERENCE_IMAGE


def test_an_unpriced_resolution_does_not_borrow_another_tiers_rate() -> None:
    only_2k = VideoPricing(generation_per_second_micro_usd={"2K": VIDEO_2K_PER_SECOND})

    assert costs.video_call_cost_micro_usd(only_2k, resolution="768P", duration_seconds=6) == 0


def test_a_capability_bills_against_its_own_pricing_section() -> None:
    pricing = MediaPricing(
        image=ImagePricing(generation_per_image_micro_usd=IMAGE_GENERATION),
        audio=AudioPricing(per_10k_characters_micro_usd=AUDIO_PER_10K),
        video=_video_pricing(),
    )

    assert costs.media_call_cost_micro_usd(pricing, capability="text_to_image") == IMAGE_GENERATION
    assert (
        costs.media_call_cost_micro_usd(
            pricing, capability="audio_generation", prompt_characters=10_000
        )
        == AUDIO_PER_10K
    )
    assert (
        costs.media_call_cost_micro_usd(
            pricing, capability="text_to_video", resolution="2K", duration_seconds=6
        )
        == 6 * VIDEO_2K_PER_SECOND
    )


def test_an_endpoint_keeps_only_the_price_sections_its_capabilities_cover() -> None:
    # A stale video price on an image-only endpoint would show up in the cost
    # report as spend on a capability the endpoint cannot even serve.
    endpoint = LlmProviderEndpoint(
        name="images",
        base_url="https://example.test",
        kind="media",
        model="gpt-image-1",
        input_modalities=["text"],
        output_modalities=["image"],
        media_pricing=MediaPricing(
            image=ImagePricing(generation_per_image_micro_usd=IMAGE_GENERATION),
            video=_video_pricing(),
        ),
    )

    assert endpoint.media_pricing.image is not None
    assert endpoint.media_pricing.video is None


def test_a_price_far_beyond_any_real_rate_is_rejected() -> None:
    # A misplaced decimal point turns $0.06 into $60_000; the ceiling is what
    # stops that reaching the router as a plausible-looking cost.
    with pytest.raises(ValueError):
        TokenPricing(input_per_million_micro_usd=10_000 * 1_000_000)


def test_an_unknown_video_resolution_is_rejected_rather_than_stored() -> None:
    with pytest.raises(ValueError):
        VideoPricing(generation_per_second_micro_usd={"4K": VIDEO_2K_PER_SECOND})


def test_the_routers_nominal_estimate_uses_the_same_arithmetic_as_the_bill() -> None:
    pricing = MediaPricing(video=_video_pricing())

    nominal = costs.nominal_media_call_cost_micro_usd(pricing, capability="text_to_video")

    assert nominal == costs.NOMINAL_VIDEO_SECONDS * VIDEO_2K_PER_SECOND


def test_a_request_aware_estimate_follows_the_jobs_own_duration() -> None:
    pricing = MediaPricing(video=_video_pricing())

    estimate = costs.estimate_media_request_cost_micro_usd(
        pricing,
        capability="text_to_video",
        params={"duration_seconds": 12, "video_options": {"resolution": "768P"}},
    )

    assert estimate == 12 * VIDEO_768P_PER_SECOND


# -- Doubao Seedance's token-formula billing --------------------------------

NO_REF_RATE = 9_722_223  # 70 元/M token
WITH_REF_RATE = 5_833_334  # 42 元/M token


def _token_video_pricing() -> TokenVideoPricing:
    return TokenVideoPricing(
        per_million_tokens_micro_usd=NO_REF_RATE,
        per_million_tokens_with_video_ref_micro_usd=WITH_REF_RATE,
    )


def test_seedance_tokens_follow_the_vendors_own_published_formula() -> None:
    # tokens = (input + output seconds) x width x height x fps / 1024, with
    # 720p's representative pixel area (1280x720) and 24fps.
    tokens = costs.seedance_video_tokens(resolution="720p", output_seconds=5)
    expected = -(-(5 * 1280 * 720 * 24) // 1024)
    assert tokens == expected


def test_seedance_bills_the_cheaper_rate_only_when_a_video_reference_is_attached() -> None:
    pricing = _token_video_pricing()

    no_ref = costs.seedance_video_cost_micro_usd(
        pricing, resolution="720p", output_seconds=5, has_video_reference=False
    )
    with_ref = costs.seedance_video_cost_micro_usd(
        pricing, resolution="720p", output_seconds=5, has_video_reference=True
    )

    tokens = costs.seedance_video_tokens(resolution="720p", output_seconds=5)
    assert no_ref == costs._ceil_div(tokens * NO_REF_RATE, costs.TOKENS_PER_PRICING_UNIT)
    assert with_ref == costs._ceil_div(tokens * WITH_REF_RATE, costs.TOKENS_PER_PRICING_UNIT)
    # The disclosed rate gap (70 vs 42 元/M) means the video-reference rate
    # must actually be cheaper, not just different.
    assert with_ref < no_ref


def test_an_undeclared_token_video_price_costs_nothing() -> None:
    assert costs.seedance_video_cost_micro_usd(None, resolution="720p", output_seconds=5) == 0
    assert (
        costs.seedance_video_cost_micro_usd(
            TokenVideoPricing(), resolution="720p", output_seconds=5
        )
        == 0
    )


def test_media_call_dispatches_to_the_seedance_formula_only_under_its_own_profile() -> None:
    pricing = MediaPricing(video=_video_pricing(), token_video=_token_video_pricing())

    seedance_cost = costs.media_call_cost_micro_usd(
        pricing,
        capability="text_to_video",
        billing_profile=costs.SEEDANCE_TOKENS_BILLING_PROFILE,
        resolution="720p",
        duration_seconds=5,
    )
    default_cost = costs.media_call_cost_micro_usd(
        pricing,
        capability="text_to_video",
        resolution="720p",
        duration_seconds=5,
    )

    tokens = costs.seedance_video_tokens(resolution="720p", output_seconds=5)
    assert seedance_cost == costs._ceil_div(tokens * NO_REF_RATE, costs.TOKENS_PER_PRICING_UNIT)
    # No `billing_profile` at all keeps today's default per-second dispatch —
    # `VideoPricing` has no "720p" rate declared in `_video_pricing()`, so it
    # prices at 0 rather than accidentally borrowing the token formula.
    assert default_cost == 0


def test_an_endpoint_keeps_token_video_pricing_only_while_it_can_serve_video() -> None:
    """`token_video` bills the same capabilities `video` does — it must be
    dropped by the exact same capability-coverage rule, or a stale Seedance
    price could survive a capability change the way a stale `video` price
    used to before that rule existed."""
    endpoint = LlmProviderEndpoint(
        name="seedance",
        base_url="https://example.test",
        kind="media",
        model="doubao-seedance-2-5-260628",
        input_modalities=["text", "image"],
        output_modalities=["video"],
        media_pricing=MediaPricing(token_video=_token_video_pricing()),
    )

    assert endpoint.media_pricing.token_video is not None

    image_only = LlmProviderEndpoint(
        name="images-only",
        base_url="https://example.test",
        kind="media",
        model="doubao-seedream-5-0-pro-260628",
        input_modalities=["text"],
        output_modalities=["image"],
        media_pricing=MediaPricing(token_video=_token_video_pricing()),
    )
    assert image_only.media_pricing.token_video is None


def test_a_model_with_no_reachable_resolution_field_still_prices_at_its_own_default() -> None:
    """Regression test for the deeper bug behind "why are there two 1080p
    price fields": most native video models (everything except MiniMax H3)
    can never have `request.resolution` set at all — the C-end request
    schema's `resolution` field only speaks H3's own `2K`/`768P` vocabulary
    (see `VideoGenerationOptions`) — so before `default_resolution` existed,
    every one of those models priced at the fixed `NOMINAL_VIDEO_RESOLUTION`
    regardless of what the operator configured for the model's *real*
    fallback resolution (`wan2.7-videoedit`'s is `720p`)."""
    per_second = 84_600  # $0.0846/s, wan2.7-videoedit's real AiHubMix rate
    pricing = MediaPricing(video=VideoPricing(generation_per_second_micro_usd={"720p": per_second}))
    request = GenerationRequest(
        job_id="job_1",
        operation="video_to_video",
        quality_tier="standard",
        prompt="",
        duration_seconds=6,
        # No `resolution` at all — the request schema cannot express `720p`.
        resolution=None,
    )

    without_default = costs.generation_attempt_cost_micro_usd(
        pricing, capability="video_to_video", request=request
    )
    with_default = costs.generation_attempt_cost_micro_usd(
        pricing, capability="video_to_video", request=request, default_resolution="720p"
    )

    # Without the model's own default, the configured `720p` price is
    # unreachable — it silently prices at 0 (unpriced "2K"), not at what was
    # actually configured.
    assert without_default == 0
    assert with_default == 6 * per_second


def test_estimate_and_nominal_also_fall_back_to_the_models_own_default_resolution() -> None:
    per_second = 41_667  # 0.3 元/秒, wan3.0-video's real DMXAPI 480P rate
    pricing = MediaPricing(video=VideoPricing(generation_per_second_micro_usd={"480P": per_second}))

    nominal = costs.nominal_media_call_cost_micro_usd(
        pricing, capability="text_to_video", default_resolution="480P"
    )
    assert nominal == costs.NOMINAL_VIDEO_SECONDS * per_second

    estimate = costs.estimate_media_request_cost_micro_usd(
        pricing,
        capability="text_to_video",
        params={"duration_seconds": 10},
        default_resolution="480P",
    )
    assert estimate == 10 * per_second

    # An explicit `video_options.resolution` on the request still wins over
    # the model's own default — the operator's own request is more specific
    # than a fallback.
    explicit = costs.estimate_media_request_cost_micro_usd(
        pricing,
        capability="text_to_video",
        params={"duration_seconds": 10, "video_options": {"resolution": "768P"}},
        default_resolution="480P",
    )
    assert explicit == 0  # "768P" was never priced for this endpoint


def test_generation_attempt_cost_reads_the_requests_own_resolution_field() -> None:
    """Regression test: the request's `resolution` field (populated from the
    job's `video_options.resolution`) must drive pricing — not `request.
    extra`, which has never actually carried a `video_options` key and used
    to make every real video request price at the nominal resolution
    regardless of what was actually requested."""
    pricing = MediaPricing(video=_video_pricing())
    request = GenerationRequest(
        job_id="job_1",
        operation="text_to_video",
        quality_tier="standard",
        prompt="a cat",
        duration_seconds=6,
        resolution="768P",
    )

    cost = costs.generation_attempt_cost_micro_usd(
        pricing, capability="text_to_video", request=request
    )

    assert cost == 6 * VIDEO_768P_PER_SECOND


def test_generation_attempt_cost_detects_a_video_reference_from_the_request() -> None:
    pricing = MediaPricing(token_video=_token_video_pricing())
    base_request = {
        "job_id": "job_1",
        "operation": "text_to_video",
        "quality_tier": "standard",
        "prompt": "a cat",
        "duration_seconds": 5,
        "resolution": "720p",
    }

    no_ref = costs.generation_attempt_cost_micro_usd(
        pricing,
        capability="text_to_video",
        request=GenerationRequest(**base_request),
        billing_profile=costs.SEEDANCE_TOKENS_BILLING_PROFILE,
    )
    with_ref = costs.generation_attempt_cost_micro_usd(
        pricing,
        capability="text_to_video",
        request=GenerationRequest(
            **base_request,
            references=[ProviderReference(object_key="ref.mp4", media_type="video")],
        ),
        billing_profile=costs.SEEDANCE_TOKENS_BILLING_PROFILE,
    )

    assert with_ref < no_ref
    assert with_ref > 0
