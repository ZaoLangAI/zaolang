"""Agent gateway: tool whitelist, LLM-selected routing and workflow shape."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.agents import base as agent_base
from app.agents import copywriter, intent_router, router, tools
from app.agents import slots as agent_slots
from app.domain.agent_skills import service as agent_skills_service
from app.domain.errors import ValidationFailed
from app.models import ProviderStat, User
from app.models.enums import AgentName, Operation, QualityTier
from app.platform_config import service as config_service
from app.platform_config.schemas import LlmProviderConfig
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
    decision = router.route(
        db, operation=Operation.TEXT_TO_IMAGE, quality_tier=QualityTier.STANDARD
    )
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

    decision = router.route(
        db, operation=Operation.TEXT_TO_IMAGE, quality_tier=QualityTier.STANDARD
    )
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


# --------------------------------------------------------------------------
# Agent variants (`AgentProfile`) and prompt slots
# --------------------------------------------------------------------------


def _seeded(db: Session) -> None:
    agent_skills_service.ensure_default_nodes(db)
    agent_skills_service.ensure_default_profiles(db)


def test_a_role_with_no_published_prompt_falls_back_to_the_module_constant(db: Session) -> None:
    """A fresh deploy has an empty `agent_skills` table; every agent must
    still run on its own hardcoded prompt rather than an empty string."""
    _seeded(db)
    prompt, profile_id = agent_skills_service.get_active_prompt(db, "safety", "BUILTIN")
    assert prompt == "BUILTIN"
    assert profile_id is not None


def test_a_node_that_binds_nothing_gets_the_roles_default_variant(db: Session) -> None:
    _seeded(db)
    default = agent_skills_service.default_profile(db, "safety")
    assert default is not None
    agent_skills_service.publish(
        db,
        profile_id=default.id,
        slot="default",
        prompt_template="DEFAULT_VARIANT",
        tool_grants=[],
        actor_user_id=None,
        reason="test",
    )

    prompt, profile_id = agent_skills_service.get_active_prompt(db, "safety", "BUILTIN")
    assert prompt == "DEFAULT_VARIANT"
    assert profile_id == default.id


def test_a_bound_agent_overrides_the_default_for_that_node_only(db: Session) -> None:
    """The whole point of letting a role have several agents: one operation's
    safety prompt can change without touching the other five."""
    _seeded(db)
    default = agent_skills_service.default_profile(db, "safety")
    assert default is not None
    agent_skills_service.publish(
        db,
        profile_id=default.id,
        slot="default",
        prompt_template="DEFAULT_VARIANT",
        tool_grants=[],
        actor_user_id=None,
        reason="test",
    )
    strict = agent_skills_service.create_profile(
        db, role="safety", key="video-strict", display_name="严格版"
    )
    agent_skills_service.publish(
        db,
        profile_id=strict.id,
        slot="default",
        prompt_template="STRICT_VARIANT",
        tool_grants=[],
        actor_user_id=None,
        reason="test",
    )

    bound, _ = agent_skills_service.get_active_prompt(db, "safety", "BUILTIN", agent_id=strict.id)
    unbound, _ = agent_skills_service.get_active_prompt(db, "safety", "BUILTIN")
    assert bound == "STRICT_VARIANT"
    assert unbound == "DEFAULT_VARIANT"


def test_an_agent_with_nothing_published_inherits_the_default_agents_prompt(
    db: Session,
) -> None:
    """Three-level fallback: bound agent, then the role default, then the
    module constant. A half-configured agent must not drop an operator back
    to the hardcoded text they already replaced."""
    _seeded(db)
    default = agent_skills_service.default_profile(db, "safety")
    assert default is not None
    agent_skills_service.publish(
        db,
        profile_id=default.id,
        slot="default",
        prompt_template="DEFAULT_VARIANT",
        tool_grants=[],
        actor_user_id=None,
        reason="test",
    )
    empty = agent_skills_service.create_profile(
        db, role="safety", key="empty", display_name="空智能体"
    )

    prompt, _ = agent_skills_service.get_active_prompt(db, "safety", "BUILTIN", agent_id=empty.id)
    assert prompt == "DEFAULT_VARIANT"


def test_a_disabled_agent_falls_back_instead_of_running_no_prompt(db: Session) -> None:
    """Publish-time validation blocks binding a disabled agent, but one can
    be disabled after a graph goes live. Generation must keep working."""
    _seeded(db)
    default = agent_skills_service.default_profile(db, "safety")
    assert default is not None
    agent_skills_service.publish(
        db,
        profile_id=default.id,
        slot="default",
        prompt_template="DEFAULT_VARIANT",
        tool_grants=[],
        actor_user_id=None,
        reason="test",
    )
    retired = agent_skills_service.create_profile(
        db, role="safety", key="retired", display_name="停用版"
    )
    agent_skills_service.publish(
        db,
        profile_id=retired.id,
        slot="default",
        prompt_template="RETIRED_VARIANT",
        tool_grants=[],
        actor_user_id=None,
        reason="test",
    )
    agent_skills_service.update_profile(db, retired.id, enabled=False)

    prompt, _ = agent_skills_service.get_active_prompt(db, "safety", "BUILTIN", agent_id=retired.id)
    assert prompt == "DEFAULT_VARIANT"


def test_an_agent_of_another_role_is_refused_at_run_time_too(db: Session) -> None:
    """Publishing rejects a cross-role binding, but a hand-edited graph or a
    reused id must not be able to run a copywriter where the pipeline reads a
    safety verdict."""
    _seeded(db)
    default = agent_skills_service.default_profile(db, "safety")
    assert default is not None
    agent_skills_service.publish(
        db,
        profile_id=default.id,
        slot="default",
        prompt_template="DEFAULT_VARIANT",
        tool_grants=[],
        actor_user_id=None,
        reason="test",
    )
    copywriter = agent_skills_service.default_profile(db, "copy")
    assert copywriter is not None

    prompt, resolved_id = agent_skills_service.get_active_prompt(
        db, "safety", "BUILTIN", agent_id=copywriter.id
    )
    assert prompt == "DEFAULT_VARIANT"
    assert resolved_id == default.id


def test_intent_routers_two_prompts_do_not_overwrite_each_other(db: Session) -> None:
    """The defect prompt slots exist to fix: `classify` and `select_provider`
    are one agent identity making two unrelated calls, so publishing one used
    to silently replace the other's instructions."""
    _seeded(db)
    profile = agent_skills_service.default_profile(db, "intent_router")
    assert profile is not None
    agent_skills_service.publish(
        db,
        profile_id=profile.id,
        slot="classify",
        prompt_template="TIER_RULES",
        tool_grants=[],
        actor_user_id=None,
        reason="test",
    )
    agent_skills_service.publish(
        db,
        profile_id=profile.id,
        slot="select_provider",
        prompt_template="PROVIDER_RULES",
        tool_grants=[],
        actor_user_id=None,
        reason="test",
    )

    classify, _ = agent_skills_service.get_active_prompt(
        db, "intent_router", "BUILTIN", slot="classify"
    )
    select, _ = agent_skills_service.get_active_prompt(
        db, "intent_router", "BUILTIN", slot="select_provider"
    )
    assert classify == "TIER_RULES"
    assert select == "PROVIDER_RULES"


def test_versions_are_numbered_per_slot_not_per_role(db: Session) -> None:
    """Shared numbering would make one slot's history look like it skipped
    versions, and would collide on the unique constraint."""
    _seeded(db)
    profile = agent_skills_service.default_profile(db, "intent_router")
    assert profile is not None
    for slot in ("classify", "select_provider", "classify"):
        agent_skills_service.publish(
            db,
            profile_id=profile.id,
            slot=slot,
            prompt_template=f"{slot}-text",
            tool_grants=[],
            actor_user_id=None,
            reason="test",
        )

    classify = agent_skills_service.list_versions(db, profile_id=profile.id, slot="classify")
    select = agent_skills_service.list_versions(db, profile_id=profile.id, slot="select_provider")
    assert [row.version for row in classify] == [2, 1]
    assert [row.version for row in select] == [1]
    assert sum(1 for row in classify if row.is_active) == 1


def test_publishing_to_a_slot_the_role_does_not_own_is_refused(db: Session) -> None:
    """A typo'd slot would create a prompt chain nothing ever reads."""
    _seeded(db)
    profile = agent_skills_service.default_profile(db, "safety")
    assert profile is not None
    with pytest.raises(ValidationFailed):
        agent_skills_service.publish(
            db,
            profile_id=profile.id,
            slot="select_provider",
            prompt_template="x",
            tool_grants=[],
            actor_user_id=None,
            reason="test",
        )


def test_every_prompt_slot_is_reachable_from_some_agent_call() -> None:
    """A declared slot with no caller is an editor tab that changes nothing;
    a caller using an undeclared slot cannot be edited at all."""
    called = {
        AgentName.SAFETY.value: {"default"},
        AgentName.PLANNER.value: {"default"},
        AgentName.QUALITY.value: {"default"},
        AgentName.COPY.value: {copywriter.SUGGEST_SLOT, copywriter.ENHANCE_SLOT},
        AgentName.INTENT_ROUTER.value: {
            intent_router.CLASSIFY_SLOT,
            intent_router.SELECT_PROVIDER_SLOT,
        },
    }
    for role, slots in called.items():
        declared = {slot.key for slot in agent_slots.slots_for(role)}
        assert declared == slots, f"{role} 的槽位声明与实际调用不一致"


# --------------------------------------------------------------------------
# Per-variant model bindings
# --------------------------------------------------------------------------


def _seed_general_endpoints(db: Session) -> None:
    config_service.set_value(
        db,
        "llm_providers",
        {
            "endpoints": {
                "pinned-ep": {
                    "name": "钉住的端点",
                    "base_url": "https://pinned.invalid",
                    "api_key": "k",
                    "kind": "general",
                    "models": ["pinned-model"],
                    "role": "primary",
                },
                "backup-ep": {
                    "name": "备用端点",
                    "base_url": "https://backup.invalid",
                    "api_key": "k",
                    "kind": "general",
                    "models": ["backup-model"],
                    "role": "backup",
                },
            }
        },
        actor_user_id=None,
        note="test bootstrap",
    )


def test_a_variant_that_pins_nothing_still_draws_from_the_shared_pool(db: Session) -> None:
    """The behaviour every variant had before per-variant bindings existed."""
    _seeded(db)
    _seed_general_endpoints(db)
    profile = agent_skills_service.default_profile(db, "safety")
    assert profile is not None

    binding = agent_base.effective_binding(db, AgentName.SAFETY.value, profile)
    assert binding.preferred_endpoint_ids == ()
    assert binding.model == agent_base.resolve_binding(db, AgentName.SAFETY.value).model


def test_a_pinned_variant_tries_its_own_endpoints_first(db: Session) -> None:
    _seeded(db)
    _seed_general_endpoints(db)
    profile = agent_skills_service.create_profile(
        db,
        role="safety",
        key="pinned",
        display_name="钉模型版",
        default_endpoint_id="pinned-ep",
        backup_endpoint_id="backup-ep",
    )

    binding = agent_base.effective_binding(db, AgentName.SAFETY.value, profile)
    assert binding.preferred_endpoint_ids == ("pinned-ep", "backup-ep")
    # The role-wide model is not one this endpoint serves, so the endpoint's
    # own model wins — otherwise the pin would send an unknown model id.
    assert binding.model == "pinned-model"


def test_pinning_an_endpoint_does_not_remove_the_rest_of_the_pool(db: Session) -> None:
    """A pin is a preference order, not a replacement pool: the shared
    endpoints stay behind it as fallbacks."""
    from app.llm import failover

    _seeded(db)
    _seed_general_endpoints(db)
    config = config_service.get_typed(db, "llm_providers", LlmProviderConfig)

    # Without a pin, `backup-ep` sorts last because it is a backup endpoint.
    assert [pair[0] for pair in failover.eligible_candidates(config)] == [
        "pinned-ep",
        "backup-ep",
    ]
    assert [
        pair[0] for pair in failover.eligible_candidates(config, preferred_ids=("backup-ep",))
    ] == ["backup-ep", "pinned-ep"]


def test_a_variant_can_override_sampling_without_pinning_an_endpoint(db: Session) -> None:
    _seeded(db)
    profile = agent_skills_service.create_profile(
        db,
        role="safety",
        key="hot",
        display_name="高温版",
        max_tokens=1_234,
        temperature_milli=900,
        reasoning_model=True,
    )

    binding = agent_base.effective_binding(db, AgentName.SAFETY.value, profile)
    assert (binding.max_tokens, binding.temperature, binding.reasoning_model) == (1234, 0.9, True)
    assert binding.preferred_endpoint_ids == ()


def test_pinning_an_endpoint_that_no_longer_exists_falls_back_to_the_pool(db: Session) -> None:
    """An operator can delete an endpoint a variant pinned. Generation must
    keep working rather than routing at a dangling id."""
    _seeded(db)
    _seed_general_endpoints(db)
    profile = agent_skills_service.create_profile(
        db, role="safety", key="stale", display_name="悬空版", default_endpoint_id="pinned-ep"
    )
    config_service.set_value(
        db, "llm_providers", {"endpoints": {}}, actor_user_id=None, note="删除端点"
    )

    binding = agent_base.effective_binding(db, AgentName.SAFETY.value, profile)
    assert binding.preferred_endpoint_ids == ()


def test_every_agent_binding_names_a_real_role_field_and_slot() -> None:
    """A binding whose config field does not exist would render a picker that
    writes into a field the backend rejects as `extra="forbid"`."""
    for node_type, spec in registry.NODE_TYPES.items():
        for binding in spec.agent_bindings:
            assert binding.config_field in spec.config_schema.model_fields, (
                f"{node_type} 绑定了不存在的配置字段 {binding.config_field}"
            )
            assert agent_slots.is_known_slot(binding.role, binding.slot), (
                f"{node_type} 绑定了 {binding.role} 不存在的槽位 {binding.slot}"
            )
