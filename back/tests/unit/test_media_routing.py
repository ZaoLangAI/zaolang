"""Dynamic router catalog and explicitly injected test providers."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.agents import router
from app.models.enums import Operation, QualityTier
from app.platform_config import service as config_service
from app.platform_config.schemas import LlmProviderConfig
from app.providers.aihubmix_media import AiHubMixMediaProvider
from tests.llm_catalog import bind_default_agents_to_catalog


def _seed_media_endpoint(
    db: Session,
    *,
    endpoint_id: str = "media-ep",
    model: str = "gpt-image-1",
    input_modalities: list[str] | None = None,
    output_modalities: list[str] | None = None,
    enabled: bool = True,
    media_pricing: dict | None = None,
) -> None:
    """Adds a media endpoint without disturbing anything already configured.

    Merging rather than replacing matters because the router's own selection
    runs through an agent, and that agent needs a general endpoint to be
    bound — wiping the pool here would make routing degrade for reasons
    unrelated to what the test is checking.
    """
    current = config_service.get_typed(db, "llm_providers", LlmProviderConfig)
    endpoints = {
        existing_id: endpoint.model_dump(mode="json")
        for existing_id, endpoint in current.endpoints.items()
    }
    endpoints[endpoint_id] = {
        "name": "AiHubMix 测试端点",
        "base_url": "https://aihubmix.invalid",
        "api_key": "test-key",
        "kind": "media",
        "enabled": enabled,
        "model": model,
        "input_modalities": input_modalities or ["image"],
        "output_modalities": output_modalities or ["image"],
        "media_pricing": media_pricing or {},
    }
    config_service.set_value(
        db,
        "llm_providers",
        {"endpoints": endpoints},
        actor_user_id=None,
        note="test bootstrap",
    )


def test_a_configured_media_endpoint_can_serve_an_operation_the_fakes_cannot(
    db: Session,
) -> None:
    """Production catalogues never include the test fakes, so `image_to_image`
    is only routable once a media endpoint is configured."""
    bind_default_agents_to_catalog(db)
    decision = router.route(
        db, operation=Operation.IMAGE_TO_IMAGE, quality_tier=QualityTier.STANDARD
    )
    assert decision.selected is None

    _seed_media_endpoint(db)
    decision = router.route(
        db, operation=Operation.IMAGE_TO_IMAGE, quality_tier=QualityTier.STANDARD
    )
    assert decision.selected is not None
    assert decision.selected.provider == "media-ep:image_to_image"
    assert isinstance(decision.provider, AiHubMixMediaProvider)


def test_narrow_modalities_remove_uncovered_operations_from_the_catalog(db: Session) -> None:
    """Only modalities that cover an operation make it routable — text→audio
    covers `audio_generation`, not `image_to_image`."""
    _seed_media_endpoint(
        db,
        model="tts-1",
        input_modalities=["text"],
        output_modalities=["audio"],
    )
    decision = router.route(
        db, operation=Operation.IMAGE_TO_IMAGE, quality_tier=QualityTier.STANDARD
    )
    assert decision.selected is None
    assert decision.reason.startswith("no_eligible_provider")


def test_disabling_the_whole_endpoint_removes_every_capability(db: Session) -> None:
    _seed_media_endpoint(db, enabled=False)
    decision = router.route(
        db, operation=Operation.IMAGE_TO_IMAGE, quality_tier=QualityTier.STANDARD
    )
    assert decision.selected is None


def test_one_endpoint_can_serve_two_independent_capabilities(db: Session) -> None:
    """One model + modalities that cover two operations yields two catalog
    entries, both dispatching to the same model id."""
    _seed_media_endpoint(
        db,
        model="multi-modal-1",
        input_modalities=["image", "text"],
        output_modalities=["image", "audio"],
    )
    catalog = router.build_catalog(db)
    assert "media-ep:image_to_image" in catalog
    assert "media-ep:audio_generation" in catalog
    assert catalog["media-ep:image_to_image"].model_or_workflow == "multi-modal-1"
    assert catalog["media-ep:audio_generation"].model_or_workflow == "multi-modal-1"


def test_production_catalog_contains_only_dynamic_routes(db: Session) -> None:
    _seed_media_endpoint(db)
    catalog = router.build_catalog(db)
    assert "fake_open_workflow" not in catalog
    assert "fake_paid_api" not in catalog
    assert "media-ep:image_to_image" in catalog


def test_h3_is_hard_filtered_when_video_parameters_exceed_its_contract(db: Session) -> None:
    _seed_media_endpoint(
        db,
        model="minimax-h3",
        input_modalities=["text", "image", "video"],
        output_modalities=["video"],
    )
    bind_default_agents_to_catalog(db)
    provider_name = "media-ep:text_to_video"
    rejected = router.route(
        db,
        operation=Operation.TEXT_TO_VIDEO,
        quality_tier=QualityTier.STANDARD,
        request_params={
            "duration_seconds": 16,
            "aspect_ratio": "16:9",
            "video_options": {"resolution": "2K", "reference_mode": "input_references"},
        },
    )
    candidate = next(item for item in rejected.candidates if item.provider == provider_name)
    assert candidate.eligible is False
    assert candidate.filter_reason == "duration_above_provider_maximum"

    accepted = router.route(
        db,
        operation=Operation.TEXT_TO_VIDEO,
        quality_tier=QualityTier.STANDARD,
        request_params={
            "duration_seconds": 15,
            "aspect_ratio": "21:9",
            "video_options": {"resolution": "2K", "reference_mode": "frame_images"},
        },
    )
    assert accepted.selected is not None
    assert accepted.selected.provider == provider_name


def test_a_configured_price_replaces_the_built_in_cost_estimate(db: Session) -> None:
    """Until an operator prices an endpoint the router works from a hardcoded
    prior, and says so — `cost_is_estimated` is what stops the LLM reading a
    guess as a quote."""
    _seed_media_endpoint(db)
    bind_default_agents_to_catalog(db)
    unpriced = router.route(
        db, operation=Operation.IMAGE_TO_IMAGE, quality_tier=QualityTier.STANDARD
    )
    guess = next(
        item for item in unpriced.candidates if item.provider == "media-ep:image_to_image"
    )
    assert guess.cost_is_estimated is True

    _seed_media_endpoint(
        db,
        media_pricing={
            "image": {
                "input_per_image_micro_usd": 2_860,
                "generation_per_image_micro_usd": 25_350,
            }
        },
    )
    priced = router.route(
        db, operation=Operation.IMAGE_TO_IMAGE, quality_tier=QualityTier.STANDARD
    )
    quoted = next(item for item in priced.candidates if item.provider == "media-ep:image_to_image")
    assert quoted.cost_is_estimated is False
    assert quoted.estimated_cost_micro_usd == 25_350


def test_cost_informs_the_llm_without_deciding_for_it(db: Session) -> None:
    """Two endpoints priced an order of magnitude apart both stay eligible.

    Cost is context on the candidate, not a filter: the hard filter is code
    (capability, modality, contract limits) and the choice is the agent's.
    """
    _seed_media_endpoint(
        db,
        endpoint_id="cheap-ep",
        media_pricing={"image": {"generation_per_image_micro_usd": 2_860}},
    )
    _seed_media_endpoint(
        db,
        endpoint_id="pricey-ep",
        media_pricing={"image": {"generation_per_image_micro_usd": 253_500}},
    )
    bind_default_agents_to_catalog(db)

    decision = router.route(
        db, operation=Operation.IMAGE_TO_IMAGE, quality_tier=QualityTier.STANDARD
    )

    by_provider = {item.provider: item for item in decision.candidates}
    cheap = by_provider["cheap-ep:image_to_image"]
    pricey = by_provider["pricey-ep:image_to_image"]
    assert cheap.eligible is True
    assert pricey.eligible is True
    assert cheap.effective_cost_micro_usd < pricey.effective_cost_micro_usd
