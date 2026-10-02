"""白膜 motion-guide references: which models may receive one, what the
schema accepts, how it is priced, and the directive the model is given."""

from __future__ import annotations

import pytest

from app.agents import router
from app.api.schemas.jobs import VideoGenerationOptions, validate_generation_params
from app.domain.costs import service as costs_service
from app.domain.media import reference_roles
from app.models.enums import MediaGenerationKind, Operation, ProviderKind
from app.providers import media_endpoints
from app.providers.base import ProviderCapability
from app.providers.dmxapi_media import video_model_profile as dmxapi_profile
from app.providers.fal_media import video_model_profile as fal_profile

MOTION_GUIDE = {"reference_mode": "input_references", "reference_video_role": "motion_guide"}


def _capability(**overrides: object) -> ProviderCapability:
    values: dict[str, object] = {
        "name": "cap:text_to_video",
        "kind": ProviderKind.COMMERCIAL_API,
        "operations": frozenset({"text_to_video"}),
        "tiers": frozenset({"standard"}),
        "quality_prior": 0.75,
        "typical_latency_ms": 1000,
        "unit_cost_micro_usd": 1,
        "model_or_workflow": "model",
        "provider_factory": lambda: None,
    }
    values.update(overrides)
    return ProviderCapability(**values)  # type: ignore[arg-type]


def test_motion_guide_needs_a_reference_to_video_model() -> None:
    params = {"duration_seconds": 6, "video_options": MOTION_GUIDE}
    assert (
        router._request_constraint_failure(_capability(), params) == "video_reference_not_supported"
    )
    assert (
        router._request_constraint_failure(_capability(accepts_video_reference=True), params)
        is None
    )
    edit_model = _capability(accepts_video_reference=True, generation_kind=MediaGenerationKind.EDIT)
    assert (
        router._request_constraint_failure(edit_model, params, has_video_source=True)
        == "edit_model_not_for_motion_guide"
    )


def test_ordinary_video_references_keep_routing_as_before() -> None:
    params = {"duration_seconds": 6, "video_options": {"reference_mode": "input_references"}}
    assert router._request_constraint_failure(_capability(), params) is None


def test_which_profiled_models_accept_a_video_reference() -> None:
    accepts = media_endpoints._accepts_video_reference
    for model in ("doubao-seedance-2-5-260628", "wan3.0-video", "MiniMax-H3"):
        profile = dmxapi_profile(model)
        assert profile is not None, model
        assert accepts("dmxapi", model, profile), model
    regeneration = dmxapi_profile("MiniMax-H3-video_regeneration")
    assert regeneration is not None
    assert not accepts("dmxapi", "MiniMax-H3-video_regeneration", regeneration)
    fal = fal_profile("minimax/h3-max")
    assert fal is not None
    assert accepts("fal", "minimax/h3-max", fal)
    assert not accepts("openai", "some-model", None)


def test_schema_rules_for_a_motion_guide() -> None:
    options = VideoGenerationOptions.model_validate(MOTION_GUIDE)
    validate_generation_params(
        Operation.TEXT_TO_VIDEO,
        duration_seconds=6,
        aspect_ratio="9:16",
        reference_asset_ids=["ast_1"],
        character_ids=["chr_1"],
        video_options=options,
    )
    with pytest.raises(ValueError, match="text_to_video"):
        validate_generation_params(
            Operation.IMAGE_TO_VIDEO,
            duration_seconds=6,
            aspect_ratio="9:16",
            reference_asset_ids=["ast_1"],
            video_options=options,
        )
    with pytest.raises(ValueError, match="参考视频"):
        validate_generation_params(
            Operation.TEXT_TO_VIDEO,
            duration_seconds=6,
            aspect_ratio="9:16",
            video_options=options,
        )


def test_directive_wraps_the_prompt_only_for_a_motion_guide() -> None:
    prompt, negative = reference_roles.apply_reference_roles("林夏推门进来", None, MOTION_GUIDE)
    assert prompt.startswith(reference_roles.MOTION_GUIDE_DIRECTIVE)
    assert prompt.endswith("林夏推门进来")
    assert negative == reference_roles.MOTION_GUIDE_NEGATIVE

    unchanged = reference_roles.apply_reference_roles("x", "模糊", {"reference_mode": "x"})
    assert unchanged == ("x", "模糊")


def test_the_estimate_bills_the_guide_clip_for_token_priced_models() -> None:
    from app.platform_config.schemas import MediaPricing

    pricing = MediaPricing.model_validate(
        {
            "token_video": {
                "per_million_tokens_micro_usd": 1_000_000,
                "per_million_tokens_with_video_ref_micro_usd": 2_000_000,
            }
        }
    )
    base = {"duration_seconds": 6, "video_options": {"resolution": "720p"}}
    guided = {
        "duration_seconds": 6,
        "video_options": {"resolution": "720p", **MOTION_GUIDE},
    }
    kwargs = {"capability": "text_to_video", "billing_profile": "seedance_tokens"}
    plain = costs_service.estimate_media_request_cost_micro_usd(pricing, params=base, **kwargs)
    with_guide = costs_service.estimate_media_request_cost_micro_usd(
        pricing, params=guided, **kwargs
    )
    # Twice the seconds (output + guide) at twice the rate.
    assert with_guide == pytest.approx(plain * 4, rel=0.01)
