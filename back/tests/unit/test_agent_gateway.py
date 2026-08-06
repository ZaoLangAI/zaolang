"""Agent gateway: tool whitelist, LLM-selected routing and workflow shape."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.agents import router, tools
from app.models import ProviderStat, User
from app.models.enums import AgentName, Operation, QualityTier
from app.platform_config import service as config_service
from app.workflows import describe_workflow, registry
from app.workflows.defaults import default_graph
from app.workflows.graph import WorkflowGraph
from app.workflows.graph import validate as validate_graph


def test_the_safety_agent_gets_no_tools_at_all(db: Session) -> None:
    """A content judgement must not depend on anything a prompt could steer."""
    assert tools.build_toolkit(db, AgentName.SAFETY) == {}


def test_every_agent_has_an_explicit_grant() -> None:
    """A new agent without an entry would otherwise fall through to whatever
    the lookup happened to return."""
    assert set(tools.AGENT_TOOL_GRANTS) == {a.value for a in AgentName}


def test_no_agent_is_granted_a_tool_that_does_not_exist() -> None:
    for agent, granted in tools.AGENT_TOOL_GRANTS.items():
        unknown = granted - set(tools.TOOL_REGISTRY)
        assert not unknown, f"{agent} 被授予了未注册的工具 {unknown}"


def test_an_agent_cannot_call_a_tool_outside_its_grant(db: Session) -> None:
    with pytest.raises(tools.UnknownToolError):
        tools.call_tool(
            db,
            AgentName.SAFETY,
            "price_operation",
            operation="text_to_image",
            quality_tier="standard",
        )


def test_an_unknown_agent_is_refused_rather_than_given_an_empty_toolkit(db: Session) -> None:
    """Silently returning no tools would make a typo look like a working agent."""
    with pytest.raises(tools.UnknownToolError):
        tools.build_toolkit(db, "definitely_not_an_agent")


def test_no_whitelisted_tool_can_move_credits_or_publish() -> None:
    """The whitelist is the security boundary: everything in it must be
    read-only or advisory."""
    import inspect

    forbidden = ("reserve", "capture", "release", "publish", "tombstone", "grant", "adjust")
    for name, func in tools.TOOL_REGISTRY.items():
        source = inspect.getsource(func)
        for marker in forbidden:
            assert f"{marker}(" not in source, f"{name} 调用了写操作 {marker}"


def test_pricing_through_a_tool_does_not_touch_any_account(db: Session, author: User) -> None:
    from app.domain.credits import service as credits_service

    before = credits_service.get_or_create_account(db, author.id).available_balance
    quoted = tools.call_tool(
        db,
        AgentName.PLANNER,
        "price_operation",
        operation=Operation.TEXT_TO_IMAGE.value,
        quality_tier=QualityTier.STANDARD.value,
    )
    assert quoted["credits"] > 0
    assert credits_service.get_or_create_account(db, author.id).available_balance == before


def test_a_private_works_parameters_are_not_readable_through_a_tool(db: Session) -> None:
    """The agent layer must not become a way around work visibility."""
    result = tools.call_tool(
        db, AgentName.PLANNER, "lookup_source_parameters", work_version_id="wv_missing"
    )
    assert result == {"found": False}


def test_routing_is_deterministic_for_identical_requests(db: Session) -> None:
    first = router.route(db, operation=Operation.TEXT_TO_IMAGE, quality_tier=QualityTier.STANDARD)
    second = router.route(db, operation=Operation.TEXT_TO_IMAGE, quality_tier=QualityTier.STANDARD)
    assert first.selected is not None
    assert first.selected.provider == second.selected.provider
    assert first.reason == second.reason


def test_every_candidate_records_why_it_was_rejected(db: Session) -> None:
    """An operator replaying a decision needs a reason for each loser, not just
    the name of the winner."""
    decision = router.route(
        db, operation=Operation.TEXT_TO_VIDEO, quality_tier=QualityTier.CINEMATIC
    )
    trace = decision.trace()
    assert len(trace) == len(router.PROVIDER_CATALOG)
    for entry in trace:
        if not entry["eligible"]:
            assert entry["filter_reason"]


def test_a_route_that_cannot_do_the_operation_is_filtered_not_scored(db: Session) -> None:
    decision = router.route(
        db, operation=Operation.TEXT_TO_VIDEO, quality_tier=QualityTier.STANDARD
    )
    open_workflow = next(c for c in decision.candidates if c.provider == "fake_open_workflow")
    assert open_workflow.eligible is False
    assert open_workflow.filter_reason == "operation_not_supported"
    assert open_workflow.effective_cost == 0


def test_disabling_a_provider_takes_effect_without_a_restart(db: Session, admin: User) -> None:
    config_service.set_value(
        db,
        "providers",
        {
            "providers": {
                "fake_open_workflow": {"enabled": False},
                "fake_paid_api": {"enabled": True},
            },
            "conservative_prior_success_rate": 0.8,
            "minimum_samples_for_stats": 20,
        },
        actor_user_id=admin.id,
        note="test",
    )

    decision = router.route(
        db, operation=Operation.TEXT_TO_IMAGE, quality_tier=QualityTier.STANDARD
    )
    assert decision.selected is not None
    assert decision.selected.provider == "fake_paid_api"
    disabled = next(c for c in decision.candidates if c.provider == "fake_open_workflow")
    assert disabled.filter_reason == "provider_disabled"


def test_disabling_everything_yields_no_route_rather_than_a_crash(db: Session, admin: User) -> None:
    config_service.set_value(
        db,
        "providers",
        {
            "providers": {
                "fake_open_workflow": {"enabled": False},
                "fake_paid_api": {"enabled": False},
            },
            "conservative_prior_success_rate": 0.8,
            "minimum_samples_for_stats": 20,
        },
        actor_user_id=admin.id,
        note="test",
    )

    decision = router.route(
        db, operation=Operation.TEXT_TO_IMAGE, quality_tier=QualityTier.STANDARD
    )
    assert decision.selected is None
    assert decision.reason.startswith("no_eligible_provider")


def test_a_single_lucky_success_does_not_outrank_a_proven_route(db: Session) -> None:
    """Without a conservative prior, one sample would dominate the score."""
    db.add(
        ProviderStat(
            provider="fake_open_workflow",
            operation=Operation.TEXT_TO_IMAGE.value,
            quality_tier=QualityTier.STANDARD.value,
            attempts=1,
            successes=1,
            total_latency_ms=100,
            total_cost_minor=2,
        )
    )
    db.flush()

    decision = router.route(
        db, operation=Operation.TEXT_TO_IMAGE, quality_tier=QualityTier.STANDARD
    )
    scored = next(c for c in decision.candidates if c.provider == "fake_open_workflow")
    from app.platform_config.schemas import ProviderConfig

    prior = config_service.get_typed(db, "providers", ProviderConfig)
    assert scored.success_rate == prior.conservative_prior_success_rate


def test_a_failing_route_gets_a_higher_effective_cost(db: Session) -> None:
    """Retries are not free, and the score has to say so."""
    db.add(
        ProviderStat(
            provider="fake_open_workflow",
            operation=Operation.TEXT_TO_IMAGE.value,
            quality_tier=QualityTier.STANDARD.value,
            attempts=100,
            successes=25,
            total_latency_ms=900_000,
            total_cost_minor=200,
        )
    )
    db.flush()

    decision = router.route(
        db, operation=Operation.TEXT_TO_IMAGE, quality_tier=QualityTier.STANDARD
    )
    flaky = next(c for c in decision.candidates if c.provider == "fake_open_workflow")
    catalogue_cost = router.PROVIDER_CATALOG["fake_open_workflow"].unit_cost_minor
    assert flaky.effective_cost > catalogue_cost


def test_llm_picks_the_lowest_effective_cost_among_eligible_candidates(db: Session) -> None:
    """Deterministic stub selection: cheapest-effective-cost eligible route
    wins, and the reason trail says an LLM made the call."""
    decision = router.route(db, operation=Operation.TEXT_TO_IMAGE, quality_tier=QualityTier.STANDARD)
    assert decision.selected is not None
    eligible = [c for c in decision.candidates if c.eligible]
    cheapest = min(eligible, key=lambda c: (c.effective_cost, c.provider))
    assert decision.selected.provider == cheapest.provider
    assert decision.reason.startswith("llm_selected")


def test_llm_selection_unavailable_yields_no_route_not_a_formula_fallback(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No fallback formula: an unavailable/invalid model response must fail
    the routing decision exactly like having no eligible provider at all."""
    from app.agents import intent_router as intent_router_agent
    from app.agents.base import AgentOutcome

    def _degraded(*args, **kwargs):  # type: ignore[no-untyped-def]
        return AgentOutcome(
            data={"selected_provider": None, "rationale": "forced_degraded"},
            raw_text="",
            degraded=True,
            model="stub:test",
            agent_run_id="agent-run-test",
        )

    monkeypatch.setattr(intent_router_agent, "select_provider", _degraded)

    decision = router.route(db, operation=Operation.TEXT_TO_IMAGE, quality_tier=QualityTier.STANDARD)
    assert decision.selected is None
    assert decision.reason == "llm_selection_unavailable"


def test_the_default_graph_uses_only_registered_node_types() -> None:
    """A node type in the seed graph that engineering forgot to register
    would otherwise only surface as a runtime crash on the first real job."""
    graph = default_graph()
    types = {n["type"] for n in graph["nodes"]}
    assert types <= set(registry.NODE_TYPES)


def test_the_default_graph_passes_structural_validation() -> None:
    """The graph every `Operation` is seeded with must itself satisfy the
    same publish-time checks an admin's custom graph is held to."""
    graph = WorkflowGraph.from_dict(default_graph())
    assert validate_graph(graph, registry_types=set(registry.NODE_TYPES)) == []


def test_the_workflow_description_is_serialisable(db: Session) -> None:
    """Falls back to the code-level default graph when no template has been
    published yet for the operation — no seed data required."""
    import json

    payload = describe_workflow(db, Operation.TEXT_TO_IMAGE.value)
    assert json.loads(json.dumps(payload))["steps"]


def test_the_declared_shape_follows_the_happy_path_in_order(db: Session) -> None:
    """A step added to the default graph but not wired into the happy path
    (or a broken port name) would silently vanish from every ops replay."""
    payload = describe_workflow(db, Operation.TEXT_TO_IMAGE.value)
    node_types = [step["node_type"] for step in payload["steps"]]
    assert node_types == [
        "safety_check",
        "planning",
        "intent_router",
        "route_score",
        "provider_generate",
        "quality_check",
        "settle_success",
    ]


def test_every_agent_node_type_names_a_real_agent(db: Session) -> None:
    names = {a.value for a in AgentName}
    payload = describe_workflow(db, Operation.TEXT_TO_IMAGE.value)
    for step in payload["steps"]:
        if step["is_agent"]:
            assert step["agent_role"] in names
