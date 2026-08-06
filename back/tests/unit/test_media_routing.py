"""Dynamic router catalog: database-configured media endpoints join the
built-in fakes and are dispatched through `AiHubMixMediaProvider`."""

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
    capabilities: dict[str, dict] | None = None,
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
                    "capabilities": capabilities
                    or {
                        "image_to_image": {
                            "model": "gpt-image-1",
                            "role": "primary",
                            "backup_order": 100,
                            "enabled": True,
                        }
                    },
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


def test_disabling_the_capability_removes_it_from_the_catalog(db: Session) -> None:
    _seed_media_endpoint(
        db,
        capabilities={
            "image_to_image": {
                "model": "gpt-image-1",
                "role": "primary",
                "backup_order": 100,
                "enabled": False,
            }
        },
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
    _seed_media_endpoint(
        db,
        capabilities={
            "image_to_image": {"model": "gpt-image-1", "role": "primary", "enabled": True},
            "audio_generation": {"model": "tts-1", "role": "backup", "enabled": True},
        },
    )
    catalog = router.build_catalog(db)
    assert "media-ep:image_to_image" in catalog
    assert "media-ep:audio_generation" in catalog
    assert catalog["media-ep:image_to_image"].model_or_workflow == "gpt-image-1"
    assert catalog["media-ep:audio_generation"].model_or_workflow == "tts-1"


def test_the_static_fakes_are_still_present_alongside_dynamic_routes(db: Session) -> None:
    _seed_media_endpoint(db)
    catalog = router.build_catalog(db)
    assert "fake_open_workflow" in catalog
    assert "fake_paid_api" in catalog
    assert "media-ep:image_to_image" in catalog
