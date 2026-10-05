"""Camera-control routes: preferred for a posed pass, never used otherwise."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.agents import intent_router, router
from app.agents.base import AgentOutcome
from app.models.enums import ProviderKind
from app.platform_config import service as config_service
from app.platform_config.schemas import LlmProviderConfig
from app.providers import media_endpoints
from app.providers.base import ProviderCapability
from app.providers.fal_media import FAL_MULTI_ANGLE_MODEL

POSED = {"extra": {"camera_pose": {"azimuth": 90, "elevation": 0, "distance": "medium"}}}


def _capability(name: str, **overrides: object) -> ProviderCapability:
    values: dict[str, object] = {
        "name": name,
        "kind": ProviderKind.COMMERCIAL_API,
        "operations": frozenset({"image_to_image"}),
        "tiers": frozenset({"standard"}),
        "quality_prior": 0.8,
        "typical_latency_ms": 1000,
        "unit_cost_micro_usd": 1,
        "model_or_workflow": name,
        "provider_factory": lambda: None,
    }
    values.update(overrides)
    return ProviderCapability(**values)  # type: ignore[arg-type]


def test_a_camera_route_is_filtered_out_without_a_pose() -> None:
    camera_route = _capability("angle", camera_control=True)
    assert router._request_constraint_failure(camera_route, {}) == "camera_pose_required"
    assert router._request_constraint_failure(camera_route, POSED) is None
    assert router._request_constraint_failure(_capability("plain"), POSED) is None


@pytest.fixture
def two_routes(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    catalog = {
        "angle": _capability("angle", camera_control=True),
        "plain": _capability("plain"),
    }
    monkeypatch.setattr(router, "build_catalog", lambda session: catalog)
    monkeypatch.setattr(router, "_load_stats", lambda *args: {})
    shown: list[list[str]] = []

    def fake_select(session: Session, *, candidates: list[dict[str, Any]], **_: object):
        names = [c["provider"] for c in candidates]
        shown.append(names)
        return AgentOutcome(
            data={"selected_provider": names[0]},
            raw_text="",
            degraded=False,
            model="m",
            agent_run_id="run",
        )

    monkeypatch.setattr(intent_router, "select_provider", fake_select)
    return shown


def test_a_posed_pass_prefers_the_camera_route(db: Session, two_routes: list[list[str]]) -> None:
    decision = router.route(
        db, operation="image_to_image", quality_tier="standard", request_params=POSED
    )
    assert decision.selected is not None and decision.selected.provider == "angle"
    assert two_routes == [["angle"]]
    plain = next(c for c in decision.candidates if c.provider == "plain")
    assert plain.filter_reason == "camera_control_preferred"


def test_a_posed_pass_falls_back_once_the_camera_route_was_tried(
    db: Session, two_routes: list[list[str]]
) -> None:
    decision = router.route(
        db,
        operation="image_to_image",
        quality_tier="standard",
        request_params=POSED,
        exclude_providers=["angle"],
    )
    assert decision.selected is not None and decision.selected.provider == "plain"


def test_an_unposed_edit_never_sees_the_camera_route(
    db: Session, two_routes: list[list[str]]
) -> None:
    router.route(db, operation="image_to_image", quality_tier="standard", request_params={})
    assert two_routes == [["plain"]]


def test_a_fal_multi_angle_endpoint_is_a_camera_capable_image_route(db: Session) -> None:
    current = config_service.get_typed(db, "llm_providers", LlmProviderConfig)
    endpoints = {k: v.model_dump(mode="json") for k, v in current.endpoints.items()}
    endpoints["fal-angle"] = {
        "name": "fal 多机位",
        "base_url": "https://queue.fal.run",
        "api_key": "test-key",
        "kind": "media",
        "enabled": True,
        "model": FAL_MULTI_ANGLE_MODEL,
        "input_modalities": ["image"],
        "output_modalities": ["image"],
        "protocol": "fal",
    }
    config_service.set_value(
        db, "llm_providers", {"endpoints": endpoints}, actor_user_id=None, note="test"
    )
    catalog = media_endpoints.dynamic_capabilities(db)
    entry = catalog["fal-angle:image_to_image"]
    assert entry.camera_control is True
    assert entry.max_image_references == 1
    assert "fal-angle:text_to_image" not in catalog
