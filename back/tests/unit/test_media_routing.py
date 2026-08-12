"""Dynamic router catalog and explicitly injected test providers."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.agents import router
from app.models.enums import Operation, QualityTier
from app.platform_config import service as config_service
from app.providers.aihubmix_media import AiHubMixMediaProvider


def _seed_media_endpoint(
    db: Session,
    *,
    endpoint_id: str = "media-ep",
    model: str = "gpt-image-1",
    input_modalities: list[str] | None = None,
    output_modalities: list[str] | None = None,
    enabled: bool = True,
) -> None:
    config_service.set_value(
        db,
        "llm_providers",
        {
            "endpoints": {
                endpoint_id: {
                    "name": "AiHubMix 测试端点",
                    "base_url": "https://aihubmix.invalid",
                    "api_key": "test-key",
                    "kind": "media",
                    "enabled": enabled,
                    "model": model,
                    "input_modalities": input_modalities or ["image"],
                    "output_modalities": output_modalities or ["image"],
                }
            }
        },
        actor_user_id=None,
        note="test bootstrap",
    )


def test_a_configured_media_endpoint_can_serve_an_operation_the_fakes_cannot(
    db: Session,
) -> None:
    """Neither fake provider declares `image_to_image`: without a configured
    endpoint the job would have nowhere to route."""
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
