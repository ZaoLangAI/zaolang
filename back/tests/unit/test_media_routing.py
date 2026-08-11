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


def test_the_static_fakes_are_still_present_alongside_dynamic_routes(db: Session) -> None:
    _seed_media_endpoint(db)
    catalog = router.build_catalog(db)
    assert "fake_open_workflow" in catalog
    assert "fake_paid_api" in catalog
    assert "media-ep:image_to_image" in catalog


def test_a_creative_agents_shortlist_filters_out_every_other_route(db: Session) -> None:
    """A route the operator did not put on the agent's list is as unusable as
    one that cannot serve the operation at all."""
    decision = router.route(
        db,
        operation=Operation.TEXT_TO_IMAGE,
        quality_tier=QualityTier.PREVIEW,
        allowed_providers={"fake_open_workflow": 100},
    )
    assert decision.selected is not None
    assert decision.selected.provider == "fake_open_workflow"

    rejected = {c.provider: c.filter_reason for c in decision.candidates if not c.eligible}
    assert rejected["fake_paid_api"] == "not_in_agent_candidates"


def test_a_shortlist_that_excludes_every_capable_route_selects_nothing(db: Session) -> None:
    _seed_media_endpoint(db)
    decision = router.route(
        db,
        operation=Operation.IMAGE_TO_IMAGE,
        quality_tier=QualityTier.STANDARD,
        allowed_providers={"some-other-endpoint:image_to_image": 100},
    )
    assert decision.selected is None
    assert "not_in_agent_candidates" in decision.reason


def test_the_configured_weight_reaches_the_agent_without_deciding_anything(
    db: Session, monkeypatch
) -> None:
    """The weight is context the selecting agent reads. Nothing in `route()`
    may rank by it — the deterministic stub picks the same provider whichever
    way the weights point."""
    seen: list[list[dict]] = []
    real_select = router.intent_router.select_provider

    def capture(session, **kwargs):
        seen.append(kwargs["candidates"])
        return real_select(session, **kwargs)

    monkeypatch.setattr(router.intent_router, "select_provider", capture)

    cheap_first = router.route(
        db,
        operation=Operation.TEXT_TO_IMAGE,
        quality_tier=QualityTier.PREVIEW,
        allowed_providers={"fake_open_workflow": 10, "fake_paid_api": 900},
    )
    cheap_last = router.route(
        db,
        operation=Operation.TEXT_TO_IMAGE,
        quality_tier=QualityTier.PREVIEW,
        allowed_providers={"fake_open_workflow": 900, "fake_paid_api": 10},
    )

    weights = {c["provider"]: c["configured_weight"] for c in seen[0]}
    assert weights == {"fake_open_workflow": 10, "fake_paid_api": 900}
    assert cheap_first.selected is not None
    assert cheap_last.selected is not None
    assert cheap_first.selected.provider == cheap_last.selected.provider


def test_routes_carry_no_configured_weight_when_no_creative_agent_is_bound(db: Session) -> None:
    decision = router.route(db, operation=Operation.TEXT_TO_IMAGE, quality_tier=QualityTier.PREVIEW)
    assert all(candidate.configured_weight is None for candidate in decision.candidates)
