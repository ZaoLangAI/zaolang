"""Dynamic router catalog and explicitly injected test providers."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.agents import router
from app.models import Asset, User
from app.models.base import new_id
from app.models.enums import (
    AssetRole,
    MediaType,
    ModerationStatus,
    Operation,
    ProviderKind,
    QualityTier,
    Visibility,
)
from app.platform_config import service as config_service
from app.platform_config.schemas import LlmProviderConfig
from app.providers.aihubmix_media import AiHubMixMediaProvider
from app.providers.base import (
    AdaptedResolution,
    ProviderCapability,
    adapt_resolution_tier,
    resolve_resolution_tier,
    studio_resolution_tiers,
    studio_tier_for_literal,
)
from app.providers.dmxapi_media import DmxApiMediaProvider
from app.providers.fal_media import FalMediaProvider
from app.providers.minimax_v2_media import MinimaxV2MediaProvider
from app.workflows import nodes as workflow_nodes
from tests.conftest import auth_header
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
    generation_kind: str = "create",
    audio_generation_kind: str = "voice",
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
        "generation_kind": generation_kind,
        "audio_generation_kind": audio_generation_kind,
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
    candidate = next(item for item in rejected_aspect.candidates if item.provider == provider_name)
    assert candidate.eligible is False

    adapted_resolution = router.route(
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
        item for item in adapted_resolution.candidates if item.provider == provider_name
    )
    # wan tops out at 1080p — 2K is a ceiling, not a must-match.
    assert candidate.eligible is True
    assert candidate.filter_reason != "resolution_not_supported"

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
    stay in the candidate set. An explicit higher ceiling (e.g. `2K`) now
    adapts downward rather than eliminating wan."""
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


def test_wan3_video_carries_its_own_default_resolution_not_h3s(db: Session) -> None:
    """`wan3.0-video` renders at `1080P` when a request leaves resolution
    unset — `2K`/`768P` is H3's vocabulary and the C-end request schema
    cannot even express `1080P` (see `VideoGenerationOptions.resolution`), so
    the catalogue entry's own `default_resolution` is the only place this
    model's real fallback resolution is recorded. (`wan2.7-videoedit`'s own
    profile deliberately declares `default_resolution=None` — AiHubMix's
    real behaviour when the field is omitted for that specific model was
    never confirmed, so the code does not guess it; `wan3.0-video` is the
    DMXAPI-profiled model this fallback is actually confirmed for.)"""
    _seed_media_endpoint(
        db,
        model="wan3.0-video",
        input_modalities=["text"],
        output_modalities=["video"],
        protocol="dmxapi",
    )
    catalog = router.build_catalog(db)
    entry = catalog["media-ep:text_to_video"]
    assert entry.default_resolution == "1080P"


def test_a_configured_price_at_the_models_own_default_resolution_is_actually_used(
    db: Session,
) -> None:
    """Regression test: before `ProviderCapability.default_resolution`
    existed, `estimate_media_request_cost_micro_usd` always fell back to the
    fixed `NOMINAL_VIDEO_RESOLUTION` ("2K") for any model whose real default
    resolution the C-end request schema cannot express — so a price
    configured under that model's actual resolution (`1080P` for
    `wan3.0-video`) was never looked up at all."""
    per_second = 166_667  # 1.2 元/秒, wan3.0-video's real DMXAPI 1080P rate
    _seed_media_endpoint(
        db,
        model="wan3.0-video",
        input_modalities=["text"],
        output_modalities=["video"],
        protocol="dmxapi",
        media_pricing={"video": {"generation_per_second_micro_usd": {"1080P": per_second}}},
    )
    bind_default_agents_to_catalog(db)

    decision = router.route(
        db,
        operation=Operation.TEXT_TO_VIDEO,
        quality_tier=QualityTier.STANDARD,
        # No `video_options.resolution` at all — exactly the shape every real
        # wan3.0-video request has, since the schema cannot name `1080P`.
        request_params={"duration_seconds": 6, "aspect_ratio": "16:9"},
    )
    candidate = next(
        item for item in decision.candidates if item.provider == "media-ep:text_to_video"
    )
    assert candidate.estimated_cost_micro_usd == 6 * per_second


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
    guess = next(item for item in unpriced.candidates if item.provider == "media-ep:image_to_image")
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
    priced = router.route(db, operation=Operation.IMAGE_TO_IMAGE, quality_tier=QualityTier.STANDARD)
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


def test_a_dmxapi_video_endpoint_carries_its_own_profile_and_dispatches_to_dmxapi(
    db: Session,
) -> None:
    """`protocol="dmxapi"` gets its own profile lookup (`dmxapi_media
    .video_model_profile`), independent of the `minimax` protocol's
    `NativeVideoModelProfile` table, and its own provider class."""
    _seed_media_endpoint(
        db,
        model="MiniMax-H3",
        input_modalities=["text", "image", "video", "audio"],
        output_modalities=["video"],
        protocol="dmxapi",
    )
    catalog = router.build_catalog(db)
    entry = catalog["media-ep:text_to_video"]
    assert entry.min_duration_seconds == 4
    assert entry.max_duration_seconds == 15
    assert entry.resolutions == frozenset({"768P", "2K"})
    assert entry.reference_modes == frozenset({"input_references", "frame_images"})

    bind_default_agents_to_catalog(db)
    decision = router.route(
        db,
        operation=Operation.TEXT_TO_VIDEO,
        quality_tier=QualityTier.STANDARD,
        request_params={
            "duration_seconds": 5,
            "aspect_ratio": "16:9",
            "video_options": {"resolution": "2K", "reference_mode": "input_references"},
        },
    )
    assert decision.selected is not None
    assert decision.selected.provider == "media-ep:text_to_video"
    assert isinstance(decision.provider, DmxApiMediaProvider)


def test_a_minimax_v2_video_endpoint_carries_its_own_profile_and_dispatches_to_minimax_v2(
    db: Session,
) -> None:
    """`protocol="minimax_v2"` is official MiniMax Video V2 / Metaso — its
    own six-ratio profile and `MinimaxV2MediaProvider`, never the AiHubMix
    `/ai/v1/videos` facade just because the model is also called H3."""
    _seed_media_endpoint(
        db,
        model="MiniMax-H3",
        input_modalities=["text", "image", "video", "audio"],
        output_modalities=["video"],
        protocol="minimax_v2",
    )
    catalog = router.build_catalog(db)
    entry = catalog["media-ep:text_to_video"]
    assert entry.min_duration_seconds == 4
    assert entry.max_duration_seconds == 15
    assert entry.resolutions == frozenset({"768P", "2K"})
    assert "3:2" not in (entry.aspect_ratios or frozenset())
    assert "adaptive" in (entry.aspect_ratios or frozenset())
    assert entry.reference_modes == frozenset({"input_references", "frame_images"})

    bind_default_agents_to_catalog(db)
    decision = router.route(
        db,
        operation=Operation.TEXT_TO_VIDEO,
        quality_tier=QualityTier.STANDARD,
        request_params={
            "duration_seconds": 5,
            "aspect_ratio": "16:9",
            "video_options": {"resolution": "2K", "reference_mode": "input_references"},
        },
    )
    assert decision.selected is not None
    assert decision.selected.provider == "media-ep:text_to_video"
    assert isinstance(decision.provider, MinimaxV2MediaProvider)


def test_a_fal_h3_max_endpoint_carries_its_own_profile_and_dispatches_to_fal(
    db: Session,
) -> None:
    """`protocol="fal"` is fal.ai's queue contract — 5–15s / 480P+768P,
    `FalMediaProvider`, never MiniMax V2 or the AiHubMix facade."""
    _seed_media_endpoint(
        db,
        model="minimax/h3-max",
        input_modalities=["text", "image", "video", "audio"],
        output_modalities=["video"],
        protocol="fal",
    )
    catalog = router.build_catalog(db)
    entry = catalog["media-ep:text_to_video"]
    assert entry.min_duration_seconds == 5
    assert entry.max_duration_seconds == 15
    assert entry.resolutions == frozenset({"480P", "768P"})
    assert entry.default_resolution == "768P"
    assert "adaptive" in (entry.aspect_ratios or frozenset())
    assert entry.reference_modes == frozenset({"input_references", "frame_images"})

    bind_default_agents_to_catalog(db)
    decision = router.route(
        db,
        operation=Operation.TEXT_TO_VIDEO,
        quality_tier=QualityTier.STANDARD,
        request_params={
            "duration_seconds": 5,
            "aspect_ratio": "16:9",
            "video_options": {"resolution": "720p", "reference_mode": "input_references"},
        },
    )
    assert decision.selected is not None
    assert decision.selected.provider == "media-ep:text_to_video"
    assert isinstance(decision.provider, FalMediaProvider)

    four_seconds = router.route(
        db,
        operation=Operation.TEXT_TO_VIDEO,
        quality_tier=QualityTier.STANDARD,
        request_params={
            "duration_seconds": 4,
            "aspect_ratio": "16:9",
            "video_options": {"resolution": "720p", "reference_mode": "input_references"},
        },
    )
    by_provider = {c.provider: c for c in four_seconds.candidates}
    assert by_provider["media-ep:text_to_video"].eligible is False


def test_dmxapi_video_regeneration_is_video_to_video_only_and_unrestricted_by_reference_mode(
    db: Session,
) -> None:
    """`MiniMax-H3-video_regeneration` requires a `base_video` reference the
    existing `input_references`/`frame_images` vocabulary cannot express —
    it is left `reference_modes=None` (unrestricted by this particular hard
    filter) rather than mis-modelled as one of those two tags; its own
    `base_video` requirement is enforced by the provider, not the router."""
    _seed_media_endpoint(
        db,
        model="MiniMax-H3-video_regeneration",
        input_modalities=["video"],
        output_modalities=["video"],
        protocol="dmxapi",
    )
    catalog = router.build_catalog(db)
    assert "media-ep:text_to_video" not in catalog
    assert "media-ep:image_to_video" not in catalog
    entry = catalog["media-ep:video_to_video"]
    assert entry.reference_modes is None
    assert entry.resolutions == frozenset({"2K"})


def test_a_dmxapi_image_endpoint_carries_no_video_profile_fields(db: Session) -> None:
    """`doubao-seedream-5-0-pro-260628` is an image model — it must not pick
    up any of the video-only profile fields just because it shares the
    `dmxapi` protocol with three video models."""
    _seed_media_endpoint(
        db,
        model="doubao-seedream-5-0-pro-260628",
        input_modalities=["text", "image"],
        output_modalities=["image"],
        protocol="dmxapi",
    )
    catalog = router.build_catalog(db)
    entry = catalog["media-ep:text_to_image"]
    assert entry.min_duration_seconds is None
    assert entry.max_duration_seconds is None
    assert entry.aspect_ratios is None
    assert entry.resolutions is None
    assert entry.reference_modes is None


def test_dmxapi_music_endpoint_carries_a_music_only_style_and_no_video_profile(
    db: Session,
) -> None:
    """`music-3.0` is BGM-only — the router's `music_generation` candidate
    for it must carry `music_styles={"music"}` (see `ProviderCapability.
    music_styles`), and none of the video-only profile fields."""
    _seed_media_endpoint(
        db,
        model="music-3.0",
        input_modalities=["text"],
        output_modalities=["audio"],
        protocol="dmxapi",
        audio_generation_kind="music",
    )
    catalog = router.build_catalog(db)
    entry = catalog["media-ep:music_generation"]
    assert entry.music_styles == frozenset({"music"})
    assert entry.reference_modes is None
    assert entry.aspect_ratios is None


def test_fal_music_and_sfx_endpoints_carry_disjoint_music_styles(db: Session) -> None:
    """The two fal apps sharing `music_generation` — BGM-only `minimax-
    music/v2.6` and SFX-only `elevenlabs/sound-effects/v2` — must resolve
    to disjoint `music_styles`, which is what lets the router's hard filter
    (`_request_constraint_failure`) tell them apart by `extra.audio_style`."""
    _seed_media_endpoint(
        db,
        endpoint_id="fal-music",
        model="minimax-music/v2.6",
        input_modalities=["text"],
        output_modalities=["audio"],
        protocol="fal",
        audio_generation_kind="music",
    )
    _seed_media_endpoint(
        db,
        endpoint_id="fal-sfx",
        model="elevenlabs/sound-effects/v2",
        input_modalities=["text"],
        output_modalities=["audio"],
        protocol="fal",
        audio_generation_kind="music",
    )
    catalog = router.build_catalog(db)
    assert catalog["fal-music:music_generation"].music_styles == frozenset({"music"})
    assert catalog["fal-sfx:music_generation"].music_styles == frozenset({"sfx"})


def test_a_fal_voice_clone_endpoint_carries_no_music_style(db: Session) -> None:
    """`music_styles` is scoped to `music_generation` only — a plain
    `audio_generation` (voice clone) candidate must not carry one, even
    though it shares the fal protocol with the music/SFX apps."""
    _seed_media_endpoint(
        db,
        model="minimax/voice-clone",
        input_modalities=["text"],
        output_modalities=["audio"],
        protocol="fal",
    )
    catalog = router.build_catalog(db)
    entry = catalog["media-ep:audio_generation"]
    assert entry.music_styles is None


def test_candidate_payload_carries_the_real_model_name_and_a_flat_quality_prior(
    db: Session,
) -> None:
    """`select_provider` must be able to tell candidates apart by real model
    identity — `provider` is only an opaque catalog key (`f"{endpoint_id}:
    {tag}"`), never a model name. `quality_prior` stays the same flat system
    default across different models: quality judgment is delegated entirely
    to the LLM's own knowledge of `model`, not a per-model number computed in
    code (see `SELECT_PROVIDER_SYSTEM_PROMPT`)."""
    _seed_media_endpoint(db, endpoint_id="model-a", model="qwen-image-3.0")
    _seed_media_endpoint(db, endpoint_id="model-b", model="doubao-seedream-5-0-pro-260628")

    catalog = router.build_catalog(db)
    capability_a = catalog["model-a:image_to_image"]
    capability_b = catalog["model-b:image_to_image"]

    payload_a = router._candidate_payload(
        router.Candidate(provider="model-a:image_to_image"), capability_a
    )
    payload_b = router._candidate_payload(
        router.Candidate(provider="model-b:image_to_image"), capability_b
    )

    assert payload_a["model"] == "qwen-image-3.0"
    assert payload_b["model"] == "doubao-seedream-5-0-pro-260628"
    assert payload_a["quality_prior"] == payload_b["quality_prior"]


def test_resolve_resolution_tier_expands_vendor_synonyms() -> None:
    """The shared resolver — not a hardcoded literal-equality check — is what
    lets a client-facing tier reach every vendor spelling that belongs to
    it, and it must never invent a match outside a candidate's own
    `resolutions`."""
    h3_resolutions = frozenset({"768P", "2K"})
    seedance_resolutions = frozenset({"480p", "720p", "1080p"})

    # "720p" is the tier both H3 (via its own "768P" token) and Seedance
    # (which spells it "720p" verbatim) can serve — each gets its own
    # spelling back, not the other's.
    assert resolve_resolution_tier("720p", h3_resolutions) == "768P"
    assert resolve_resolution_tier("720p", seedance_resolutions) == "720p"

    # "2K" is H3-exclusive; Seedance has nothing in that tier.
    assert resolve_resolution_tier("2K", h3_resolutions) == "2K"
    assert resolve_resolution_tier("2K", seedance_resolutions) is None

    # "1080p" is Seedance-only; H3 has nothing in that tier (768P/2K, no
    # true 1080p equivalent).
    assert resolve_resolution_tier("1080p", h3_resolutions) is None
    assert resolve_resolution_tier("1080p", seedance_resolutions) == "1080p"

    # Omitted tier (a video remix) or an unknown `available` set both mean
    # "nothing to resolve", never a guess.
    assert resolve_resolution_tier(None, h3_resolutions) is None
    assert resolve_resolution_tier("720p", None) is None


def test_adapt_resolution_tier_only_walks_down_then_lowest() -> None:
    """User pick is a ceiling: exact, else highest strictly lower, else the
    model's lowest tier. 1080p must never become 2K."""
    h3 = frozenset({"768P", "2K"})
    seedance = frozenset({"480p", "720p", "1080p"})

    assert adapt_resolution_tier("1080p", h3) == AdaptedResolution(
        studio_tier="720p", vendor_literal="768P", kind="downgrade"
    )
    assert adapt_resolution_tier("2K", h3) == AdaptedResolution(
        studio_tier="2K", vendor_literal="2K", kind="exact"
    )
    assert adapt_resolution_tier("2K", seedance) == AdaptedResolution(
        studio_tier="1080p", vendor_literal="1080p", kind="downgrade"
    )
    assert adapt_resolution_tier("480p", h3) == AdaptedResolution(
        studio_tier="720p", vendor_literal="768P", kind="upgrade"
    )
    assert adapt_resolution_tier(None, h3) is None
    assert adapt_resolution_tier("1080p", None) == AdaptedResolution(
        studio_tier="1080p", vendor_literal="1080p", kind="exact"
    )
    assert adapt_resolution_tier("1080p", frozenset({"nonsense"})) is None
    assert studio_resolution_tiers(h3) == ["720p", "2K"]
    assert studio_tier_for_literal("768P") == "720p"
    assert studio_tier_for_literal("2K") == "2K"


def test_provider_call_and_route_summary_use_adapted_vendor_literal() -> None:
    capability = ProviderCapability(
        name="h3:text_to_video",
        kind=ProviderKind.COMMERCIAL_API,
        operations=frozenset({"text_to_video"}),
        tiers=frozenset({"standard"}),
        quality_prior=0.75,
        typical_latency_ms=1000,
        unit_cost_micro_usd=1,
        model_or_workflow="MiniMax-H3",
        provider_factory=lambda: None,  # type: ignore[return-value]
        resolutions=frozenset({"768P", "2K"}),
    )
    params = {"video_options": {"resolution": "1080p", "reference_mode": "input_references"}}
    assert workflow_nodes._vendor_resolution_for(capability, params) == "768P"
    fields = workflow_nodes._resolution_adapt_fields(capability, params)
    assert fields["requested_resolution"] == "1080p"
    assert fields["adapted_resolution"] == "720p"
    assert fields["adapted_vendor_resolution"] == "768P"
    assert fields["resolution_adapt_kind"] == "downgrade"
    assert workflow_nodes._vendor_resolution_for(capability, {"video_options": {}}) is None


def test_unadaptable_resolutions_still_hard_filter() -> None:
    capability = ProviderCapability(
        name="broken:text_to_video",
        kind=ProviderKind.COMMERCIAL_API,
        operations=frozenset({"text_to_video"}),
        tiers=frozenset({"standard"}),
        quality_prior=0.75,
        typical_latency_ms=1000,
        unit_cost_micro_usd=1,
        model_or_workflow="broken",
        provider_factory=lambda: None,  # type: ignore[return-value]
        resolutions=frozenset({"nonsense"}),
    )
    assert (
        router._request_constraint_failure(
            capability,
            {"video_options": {"resolution": "1080p", "reference_mode": "input_references"}},
        )
        == "resolution_not_supported"
    )


def test_a_resolution_tier_lets_minimax_and_lowercase_p_models_compete(db: Session) -> None:
    """The whole point of the tier system: a `"720p"` request must make both
    `minimax-h3` (whose own token for that tier is `"768P"`) and
    `doubao-seedance-2-5-260628` (which spells it `"720p"` verbatim)
    eligible for the same job — before this, the two could never appear as
    candidates for the same explicit resolution request."""
    _seed_media_endpoint(
        db,
        endpoint_id="h3-ep",
        model="minimax-h3",
        input_modalities=["text", "image"],
        output_modalities=["video"],
        protocol="minimax",
    )
    _seed_media_endpoint(
        db,
        endpoint_id="seedance-ep",
        model="doubao-seedance-2-5-260628",
        input_modalities=["text", "image"],
        output_modalities=["video"],
        protocol="dmxapi",
    )
    bind_default_agents_to_catalog(db)

    decision = router.route(
        db,
        operation=Operation.TEXT_TO_VIDEO,
        quality_tier=QualityTier.STANDARD,
        request_params={
            "duration_seconds": 5,
            "aspect_ratio": "16:9",
            "video_options": {"resolution": "720p", "reference_mode": "input_references"},
        },
    )

    by_provider = {c.provider: c for c in decision.candidates}
    assert by_provider["h3-ep:text_to_video"].eligible is True
    assert by_provider["seedance-ep:text_to_video"].eligible is True

    # "2K" is above Seedance's ceiling (1080p) but still adaptable — both
    # stay eligible; costing/call use the adapted vendor literal.
    two_k_decision = router.route(
        db,
        operation=Operation.TEXT_TO_VIDEO,
        quality_tier=QualityTier.STANDARD,
        request_params={
            "duration_seconds": 5,
            "aspect_ratio": "16:9",
            "video_options": {"resolution": "2K", "reference_mode": "input_references"},
        },
    )
    by_provider_2k = {c.provider: c for c in two_k_decision.candidates}
    assert by_provider_2k["h3-ep:text_to_video"].eligible is True
    assert by_provider_2k["seedance-ep:text_to_video"].eligible is True
    assert by_provider_2k["seedance-ep:text_to_video"].filter_reason != "resolution_not_supported"


def test_estimated_cost_prices_the_resolved_literal_not_the_raw_tier(db: Session) -> None:
    """`minimax-h3` is priced under its own `"768P"` token. A client request
    for the `"720p"` tier must still price it at that real rate — reading
    the unresolved tier token as a literal pricing-table key would silently
    look up nothing and read the candidate as free."""
    per_second = 80_000
    _seed_media_endpoint(
        db,
        endpoint_id="h3-ep",
        model="minimax-h3",
        input_modalities=["text", "image"],
        output_modalities=["video"],
        protocol="minimax",
        media_pricing={"video": {"generation_per_second_micro_usd": {"768P": per_second}}},
    )
    bind_default_agents_to_catalog(db)

    decision = router.route(
        db,
        operation=Operation.TEXT_TO_VIDEO,
        quality_tier=QualityTier.STANDARD,
        request_params={
            "duration_seconds": 5,
            "aspect_ratio": "16:9",
            "video_options": {"resolution": "720p", "reference_mode": "input_references"},
        },
    )
    candidate = next(item for item in decision.candidates if item.provider == "h3-ep:text_to_video")
    assert candidate.eligible is True
    assert candidate.estimated_cost_micro_usd == 5 * per_second


def test_estimated_cost_prices_adapted_downgrade_not_the_raw_ceiling(db: Session) -> None:
    """H3 has no 1080p; adapting to 720p/`768P` must price the 768P row."""
    per_second = 80_000
    _seed_media_endpoint(
        db,
        endpoint_id="h3-ep",
        model="minimax-h3",
        input_modalities=["text", "image"],
        output_modalities=["video"],
        protocol="minimax",
        media_pricing={"video": {"generation_per_second_micro_usd": {"768P": per_second}}},
    )
    bind_default_agents_to_catalog(db)

    decision = router.route(
        db,
        operation=Operation.TEXT_TO_VIDEO,
        quality_tier=QualityTier.STANDARD,
        request_params={
            "duration_seconds": 5,
            "aspect_ratio": "16:9",
            "video_options": {"resolution": "1080p", "reference_mode": "input_references"},
        },
    )
    candidate = next(item for item in decision.candidates if item.provider == "h3-ep:text_to_video")
    assert candidate.eligible is True
    assert candidate.estimated_cost_micro_usd == 5 * per_second
    adapted = router._resolved_request_params(
        router.build_catalog(db)["h3-ep:text_to_video"],
        {
            "duration_seconds": 5,
            "video_options": {"resolution": "1080p", "reference_mode": "input_references"},
        },
    )
    assert adapted["video_options"]["resolution"] == "768P"


def test_forced_model_picks_deterministically_without_calling_the_selecting_agent(
    db: Session, monkeypatch
) -> None:
    """`GenerationParams.forced_model`'s whole point: two endpoints that both
    serve the exact same model must still resolve to one deterministic
    winner (sorted by `provider`) without ever asking `intent_router
    .select_provider` — a real call would show up as an `AgentRun`; skipping
    it is the "跳过工作流节点" behaviour this feature promises."""
    _seed_media_endpoint(
        db,
        endpoint_id="z-vendor",
        model="doubao-seedream-5-0-pro-260628",
        input_modalities=["text"],
        output_modalities=["image"],
    )
    _seed_media_endpoint(
        db,
        endpoint_id="a-vendor",
        model="doubao-seedream-5-0-pro-260628",
        input_modalities=["text"],
        output_modalities=["image"],
    )

    called = False

    def _fail_if_called(*_args: object, **_kwargs: object) -> object:
        nonlocal called
        called = True
        raise AssertionError("intent_router.select_provider must not be called")

    monkeypatch.setattr(router.intent_router, "select_provider", _fail_if_called)

    decision = router.route(
        db,
        operation=Operation.TEXT_TO_IMAGE,
        quality_tier=QualityTier.STANDARD,
        forced_model="doubao-seedream-5-0-pro-260628",
    )

    assert called is False
    assert decision.selected is not None
    # "a-vendor" sorts before "a-vendor:text_to_image" vs "z-vendor:...";
    # the deterministic tie-break is by `provider` name, not insertion order.
    assert decision.selected.provider == "a-vendor:text_to_image"
    assert decision.capability is not None
    assert decision.capability.model_or_workflow == "doubao-seedream-5-0-pro-260628"
    assert decision.reason == "user_forced_model:doubao-seedream-5-0-pro-260628"
    assert decision.agent_run_id is None


def test_forced_model_unavailable_fails_without_calling_the_selecting_agent(
    db: Session, monkeypatch
) -> None:
    """No survivor matching `forced_model` is a hard failure — never a
    silent fallback to the normal LLM-driven pick among whatever else is
    eligible."""
    _seed_media_endpoint(
        db,
        endpoint_id="only-ep",
        model="doubao-seedream-5-0-pro-260628",
        input_modalities=["text"],
        output_modalities=["image"],
    )

    called = False

    def _fail_if_called(*_args: object, **_kwargs: object) -> object:
        nonlocal called
        called = True
        raise AssertionError("intent_router.select_provider must not be called")

    monkeypatch.setattr(router.intent_router, "select_provider", _fail_if_called)

    decision = router.route(
        db,
        operation=Operation.TEXT_TO_IMAGE,
        quality_tier=QualityTier.STANDARD,
        forced_model="some-other-model-not-configured",
    )

    assert called is False
    assert decision.selected is None
    assert decision.reason == "forced_model_unavailable"


def test_list_generation_models_exposes_h3_studio_tiers(
    client: TestClient, author, db: Session
) -> None:
    """DMXAPI MiniMax-H3 advertises 768P/2K; the picker must see 720p+2K."""
    _seed_media_endpoint(
        db,
        endpoint_id="h3-ep",
        model="MiniMax-H3",
        input_modalities=["text", "image"],
        output_modalities=["video"],
        protocol="dmxapi",
    )
    response = client.get(
        "/v1/generation-jobs/models",
        params={"operation": "image_to_video"},
        headers=auth_header(author),
    )
    assert response.status_code == 200, response.text
    h3 = next(entry for entry in response.json()["models"] if entry["model"] == "MiniMax-H3")
    assert h3["resolutions"] == ["720p", "2K"]
    assert h3["default_resolution"] == "2K"


def _reference_asset(db: Session, owner: User, media_type: MediaType) -> Asset:
    asset = Asset(
        owner_user_id=owner.id,
        object_key=f"test/{new_id('obj')}.bin",
        media_type=media_type,
        mime_type="video/mp4" if media_type == MediaType.VIDEO else "image/png",
        size_bytes=128,
        checksum_sha256="a" * 64,
        role=AssetRole.GENERATION_REFERENCE,
        moderation_status=ModerationStatus.APPROVED,
        visibility=Visibility.PRIVATE,
    )
    db.add(asset)
    db.flush()
    return asset


def test_edit_class_video_model_is_filtered_without_a_video_source(db: Session) -> None:
    _seed_media_endpoint(
        db,
        model="wan2.7-videoedit",
        input_modalities=["text", "video"],
        output_modalities=["video"],
        protocol="minimax",
        generation_kind="edit",
    )
    bind_default_agents_to_catalog(db)
    decision = router.route(
        db,
        operation=Operation.TEXT_TO_VIDEO,
        quality_tier=QualityTier.STANDARD,
        request_params={
            "duration_seconds": 8,
            "aspect_ratio": "16:9",
            "video_options": {"resolution": "1080p", "reference_mode": "input_references"},
        },
    )
    provider_name = "media-ep:text_to_video"
    candidate = next(item for item in decision.candidates if item.provider == provider_name)
    assert candidate.eligible is False
    assert candidate.filter_reason == "edit_model_requires_video_source"


def test_edit_class_video_model_stays_eligible_for_video_to_video(db: Session) -> None:
    _seed_media_endpoint(
        db,
        model="wan2.7-videoedit",
        input_modalities=["text", "video"],
        output_modalities=["video"],
        protocol="minimax",
        generation_kind="edit",
    )
    bind_default_agents_to_catalog(db)
    decision = router.route(
        db,
        operation=Operation.VIDEO_TO_VIDEO,
        quality_tier=QualityTier.STANDARD,
        request_params={
            "duration_seconds": 8,
            "aspect_ratio": "16:9",
            "video_options": {"resolution": "720p", "reference_mode": "input_references"},
        },
    )
    assert decision.selected is not None
    assert decision.selected.provider == "media-ep:video_to_video"


def test_edit_class_video_model_is_eligible_when_a_reference_is_video(
    db: Session, author: User
) -> None:
    clip = _reference_asset(db, author, MediaType.VIDEO)
    _seed_media_endpoint(
        db,
        model="wan2.7-videoedit",
        input_modalities=["text", "video"],
        output_modalities=["video"],
        protocol="minimax",
        generation_kind="edit",
    )
    bind_default_agents_to_catalog(db)
    decision = router.route(
        db,
        operation=Operation.TEXT_TO_VIDEO,
        quality_tier=QualityTier.STANDARD,
        request_params={
            "duration_seconds": 8,
            "aspect_ratio": "16:9",
            "reference_asset_ids": [clip.id],
            "video_options": {"resolution": "1080p", "reference_mode": "input_references"},
        },
    )
    assert decision.selected is not None
    assert decision.selected.provider == "media-ep:text_to_video"


def test_a_still_reference_does_not_count_as_a_video_source_for_edit_models(
    db: Session, author: User
) -> None:
    still = _reference_asset(db, author, MediaType.IMAGE)
    _seed_media_endpoint(
        db,
        model="wan2.7-videoedit",
        input_modalities=["text", "video"],
        output_modalities=["video"],
        protocol="minimax",
        generation_kind="edit",
    )
    bind_default_agents_to_catalog(db)
    decision = router.route(
        db,
        operation=Operation.TEXT_TO_VIDEO,
        quality_tier=QualityTier.STANDARD,
        request_params={
            "duration_seconds": 8,
            "aspect_ratio": "16:9",
            "reference_asset_ids": [still.id],
            "video_options": {"resolution": "1080p", "reference_mode": "input_references"},
        },
    )
    provider_name = "media-ep:text_to_video"
    candidate = next(item for item in decision.candidates if item.provider == provider_name)
    assert candidate.eligible is False
    assert candidate.filter_reason == "edit_model_requires_video_source"


def test_list_generation_models_hides_edit_class_on_text_to_video(
    client: TestClient, author: User, db: Session
) -> None:
    _seed_media_endpoint(
        db,
        endpoint_id="edit-ep",
        model="wan2.7-videoedit",
        input_modalities=["text", "video"],
        output_modalities=["video"],
        protocol="minimax",
        generation_kind="edit",
    )
    _seed_media_endpoint(
        db,
        endpoint_id="h3-ep",
        model="MiniMax-H3",
        input_modalities=["text", "image"],
        output_modalities=["video"],
        protocol="dmxapi",
    )
    hidden = client.get(
        "/v1/generation-jobs/models",
        params={"operation": "text_to_video"},
        headers=auth_header(author),
    )
    assert hidden.status_code == 200, hidden.text
    hidden_models = {entry["model"] for entry in hidden.json()["models"]}
    assert "wan2.7-videoedit" not in hidden_models
    assert "MiniMax-H3" in hidden_models

    shown = client.get(
        "/v1/generation-jobs/models",
        params={"operation": "video_to_video"},
        headers=auth_header(author),
    )
    assert shown.status_code == 200, shown.text
    shown_models = {entry["model"] for entry in shown.json()["models"]}
    assert "wan2.7-videoedit" in shown_models
