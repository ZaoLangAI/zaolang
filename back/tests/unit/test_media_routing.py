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
    protocol: str | None = None,
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
        "protocol": protocol,
    }
    config_service.set_value(
        db,
        "llm_providers",
        {"endpoints": endpoints},
        actor_user_id=None,
        note="test bootstrap",
    )


def _seed_general_endpoint(
    db: Session,
    *,
    endpoint_id: str = "general-ep",
    model: str = "qwen-vl-max",
    input_modalities: list[str] | None = None,
    enabled: bool = True,
) -> None:
    """A `kind="general"` endpoint, optionally declaring video input support.

    Mirrors `_seed_media_endpoint`'s merge-not-replace behaviour. Unlike a
    media endpoint, `input_modalities=None` here means "text only" (the
    validator's default), not "whatever `_seed_media_endpoint` defaults to".
    """
    current = config_service.get_typed(db, "llm_providers", LlmProviderConfig)
    endpoints = {
        existing_id: endpoint.model_dump(mode="json")
        for existing_id, endpoint in current.endpoints.items()
    }
    endpoints[endpoint_id] = {
        "name": "通用测试端点",
        "base_url": "https://general.invalid",
        "api_key": "test-key",
        "kind": "general",
        "role": "backup",
        "enabled": enabled,
        "model": model,
        "input_modalities": input_modalities or [],
    }
    config_service.set_value(
        db,
        "llm_providers",
        {"endpoints": endpoints},
        actor_user_id=None,
        note="test bootstrap",
    )


def test_a_general_endpoint_without_video_never_enters_the_video_analysis_catalog(
    db: Session,
) -> None:
    """Strict validation: a general endpoint that hasn't declared video input
    must never be selectable for `video_analysis`."""
    _seed_general_endpoint(db, input_modalities=["image"])
    catalog = router.build_catalog(db)
    assert "general-ep:video_analysis" not in catalog
    assert not any(key.startswith("general-ep:") for key in catalog)


def test_a_general_endpoint_declaring_video_enters_the_video_analysis_catalog(
    db: Session,
) -> None:
    _seed_general_endpoint(db, input_modalities=["video"])
    catalog = router.build_catalog(db)
    entry = catalog["general-ep:video_analysis"]
    assert entry.model_or_workflow == "qwen-vl-max"
    assert entry.operations == frozenset({"video_analysis"})


def test_a_general_endpoint_with_video_can_be_selected_for_video_analysis(db: Session) -> None:
    """End-to-end: `router.route` actually dispatches `video_analysis` to a
    general endpoint once it declares video support, reusing the same
    `AiHubMixMediaProvider` a media endpoint would use."""
    bind_default_agents_to_catalog(db)
    decision = router.route(
        db, operation=Operation.VIDEO_ANALYSIS, quality_tier=QualityTier.STANDARD
    )
    assert decision.selected is None

    _seed_general_endpoint(db, input_modalities=["video"])
    decision = router.route(
        db, operation=Operation.VIDEO_ANALYSIS, quality_tier=QualityTier.STANDARD
    )
    assert decision.selected is not None
    assert decision.selected.provider == "general-ep:video_analysis"
    assert isinstance(decision.provider, AiHubMixMediaProvider)


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


def test_wan_videoedit_is_hard_filtered_by_its_own_narrower_profile(db: Session) -> None:
    """`wan2.7-videoedit`'s profile (2-10s, five aspect ratios, 720p/1080p) is
    narrower than H3's — the router must key its hard filter off the
    per-model profile table, not a single duration/aspect-ratio constant
    shared with H3."""
    _seed_media_endpoint(
        db,
        model="wan2.7-videoedit",
        input_modalities=["text", "video"],
        output_modalities=["video"],
        protocol="minimax",
    )
    bind_default_agents_to_catalog(db)
    provider_name = "media-ep:video_to_video"

    # An explicit `2K` is H3-only and still hard-filters wan. A remix
    # omits `resolution` entirely so this filter does not fire — see
    # `test_omitted_resolution_does_not_hard_filter_wan_videoedit`.
    rejected = router.route(
        db,
        operation=Operation.VIDEO_TO_VIDEO,
        quality_tier=QualityTier.STANDARD,
        request_params={
            "duration_seconds": 12,
            "aspect_ratio": "16:9",
            "video_options": {"resolution": "720p", "reference_mode": "input_references"},
        },
    )
    candidate = next(item for item in rejected.candidates if item.provider == provider_name)
    assert candidate.eligible is False
    assert candidate.filter_reason == "duration_above_provider_maximum"

    rejected_aspect = router.route(
        db,
        operation=Operation.VIDEO_TO_VIDEO,
        quality_tier=QualityTier.STANDARD,
        request_params={
            "duration_seconds": 8,
            "aspect_ratio": "21:9",
            "video_options": {"resolution": "720p", "reference_mode": "input_references"},
        },
    )
    candidate = next(
        item for item in rejected_aspect.candidates if item.provider == provider_name
    )
    assert candidate.eligible is False

    rejected_resolution = router.route(
        db,
        operation=Operation.VIDEO_TO_VIDEO,
        quality_tier=QualityTier.STANDARD,
        request_params={
            "duration_seconds": 8,
            "aspect_ratio": "16:9",
            "video_options": {"resolution": "2K", "reference_mode": "input_references"},
        },
    )
    candidate = next(
        item for item in rejected_resolution.candidates if item.provider == provider_name
    )
    assert candidate.eligible is False
    assert candidate.filter_reason == "resolution_not_supported"

    accepted = router.route(
        db,
        operation=Operation.VIDEO_TO_VIDEO,
        quality_tier=QualityTier.STANDARD,
        request_params={
            "duration_seconds": 8,
            "aspect_ratio": "16:9",
            "video_options": {"resolution": "720p", "reference_mode": "input_references"},
        },
    )
    assert accepted.selected is not None
    assert accepted.selected.provider == provider_name


def test_omitted_resolution_does_not_hard_filter_wan_videoedit(db: Session) -> None:
    """A video remix omits `video_options.resolution` so cheaper edit models
    stay in the candidate set. Only an explicit H3-only value (e.g. `2K`)
    may eliminate wan here."""
    _seed_media_endpoint(
        db,
        model="wan2.7-videoedit",
        input_modalities=["text", "video"],
        output_modalities=["video"],
        protocol="minimax",
    )
    bind_default_agents_to_catalog(db)
    provider_name = "media-ep:video_to_video"
    decision = router.route(
        db,
        operation=Operation.VIDEO_TO_VIDEO,
        quality_tier=QualityTier.STANDARD,
        request_params={
            "duration_seconds": 8,
            "aspect_ratio": "16:9",
            "video_options": {"reference_mode": "input_references"},
        },
    )
    candidate = next(item for item in decision.candidates if item.provider == provider_name)
    assert candidate.eligible is True
    assert candidate.filter_reason != "resolution_not_supported"
    assert decision.selected is not None
    assert decision.selected.provider == provider_name


def test_wan_videoedit_never_advertises_frame_images_unlike_h3(db: Session) -> None:
    """`frame_images` is an H3-only concept — a differently-profiled native
    video model must not be offered it."""
    _seed_media_endpoint(
        db,
        model="wan2.7-videoedit",
        input_modalities=["text", "video"],
        output_modalities=["video"],
        protocol="minimax",
    )
    catalog = router.build_catalog(db)
    entry = catalog["media-ep:video_to_video"]
    assert entry.reference_modes == frozenset({"input_references"})


def test_an_openai_protocol_video_endpoint_carries_no_native_hard_filter(db: Session) -> None:
    """The native `NativeVideoModelProfile` table only applies to the
    `minimax` protocol's `/ai/v1/videos` contract — an `openai`-protocol
    video endpoint must not inherit H3's or wan's physical limits just
    because it happens to share a model name lookup path."""
    _seed_media_endpoint(
        db,
        endpoint_id="openai-video-ep",
        model="wan2.7-videoedit",
        input_modalities=["text"],
        output_modalities=["video"],
        protocol="openai",
    )
    catalog = router.build_catalog(db)
    entry = catalog["openai-video-ep:text_to_video"]
    assert entry.min_duration_seconds is None
    assert entry.max_duration_seconds is None
    assert entry.aspect_ratios is None
    assert entry.resolutions is None
    assert entry.reference_modes is None


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
