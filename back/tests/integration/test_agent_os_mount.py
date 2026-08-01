"""AgentOS is mounted alongside the product API, never on top of it."""

from __future__ import annotations

import pytest

from app.config import get_settings
from app.main import create_app


@pytest.fixture
def with_agent_os(monkeypatch):  # type: ignore[no-untyped-def]
    monkeypatch.setattr(get_settings(), "agent_os_enabled", True, raising=False)


@pytest.fixture
def without_agent_os(monkeypatch):  # type: ignore[no-untyped-def]
    monkeypatch.setattr(get_settings(), "agent_os_enabled", False, raising=False)


def _paths(app) -> set[str]:  # type: ignore[no-untyped-def]
    return set(app.openapi()["paths"])


def test_the_console_is_off_by_default(without_agent_os) -> None:
    """It exposes model bindings and lets a human drive agents, so it is not
    something to serve unasked."""
    paths = _paths(create_app())
    assert not any(p.startswith("/agents") for p in paths)
    assert any(p.startswith("/v1") for p in paths)


def test_enabling_the_console_adds_routes_without_removing_any(
    without_agent_os, with_agent_os
) -> None:
    baseline_settings = get_settings()
    baseline_settings.agent_os_enabled = False
    before = _paths(create_app())

    baseline_settings.agent_os_enabled = True
    after = _paths(create_app())

    assert before <= after, f"挂载 AgentOS 后丢失了接口: {sorted(before - after)}"
    assert any(p.startswith("/agents") for p in after)


def test_the_product_contract_wins_a_route_conflict(with_agent_os) -> None:
    """AgentOS also serves a health endpoint; ours must be the one that
    answers, or monitoring would silently start probing the wrong thing."""
    app = create_app()
    spec = app.openapi()
    assert spec["info"]["title"] == "造浪 zaolang API"

    healthz = spec["paths"]["/healthz"]["get"]
    assert "健康" in (healthz.get("summary") or "") or "healthz" in (
        healthz.get("operationId") or ""
    )


def test_a_broken_agent_definition_does_not_take_the_api_down(with_agent_os, monkeypatch) -> None:
    """The console is auxiliary. Losing it must degrade to "no console", not
    "no service"."""
    from app import teams

    def explode(_session):  # type: ignore[no-untyped-def]
        raise RuntimeError("模型绑定损坏")

    monkeypatch.setattr(teams, "build_generation_gateway_team", explode)

    paths = _paths(create_app())
    assert any(p.startswith("/v1") for p in paths)
