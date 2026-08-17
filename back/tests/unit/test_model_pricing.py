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
    VideoPricing,
)

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
    assert (
        costs.llm_call_cost_micro_usd(None, prompt_tokens=1_000_000, completion_tokens=0) == 0
    )


def test_an_image_edit_pays_for_what_it_consumed_and_what_it_produced() -> None:
    pricing = ImagePricing(
        input_per_image_micro_usd=IMAGE_INPUT,
        generation_per_image_micro_usd=IMAGE_GENERATION,
    )

    cost = costs.image_call_cost_micro_usd(pricing, input_images=3, generated_images=1)

    assert cost == 3 * IMAGE_INPUT + IMAGE_GENERATION


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

    assert (
        costs.media_call_cost_micro_usd(pricing, capability="text_to_image") == IMAGE_GENERATION
    )
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
