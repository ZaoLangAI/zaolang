"""Agent gateway: tool whitelist, LLM-selected routing and workflow shape."""

from __future__ import annotations

import json

import pytest
from sqlalchemy.orm import Session

from app.agents import base as agent_base
from app.agents import copywriter, editor_planner, intent_router, planner, router, tools
from app.agents import slots as agent_slots
from app.domain.agent_skills import service as agent_skills_service
from app.domain.errors import ValidationFailed
from app.models import AgentRun, ProviderStat, User
from app.models.enums import AgentName, Operation, QualityTier
from app.platform_config import service as config_service
from app.platform_config.schemas import LlmProviderConfig
from app.workflows import describe_workflow, registry
from app.workflows.defaults import default_graph
from app.workflows.graph import WorkflowGraph
from app.workflows.graph import validate as validate_graph
from tests.fake_provider_catalog import build_fake_catalog


@pytest.fixture(autouse=True)
def _inject_test_media_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(router, "build_catalog", lambda session: build_fake_catalog())


def test_the_safety_agent_gets_no_tools_at_all(db: Session) -> None:
    """A content judgement must not depend on anything a prompt could steer."""
    assert tools.build_toolkit(db, AgentName.SAFETY) == {}


def test_realistic_gang_violence_is_sent_to_review_rather_than_approved(db: Session) -> None:
    """Written policy allows adult artistic expression, but a written, realistic
    brawl/gore scene is not a blanket approval — it must land in the human
    review queue instead of being auto-approved."""
    from app.agents import safety
    from app.models.enums import ModerationStage, ModerationStatus

    result = safety.review(
        db,
        text="生成一个社会帮派港风街道斗殴的场景",
        stage=ModerationStage.PRE_GENERATION,
        subject_type="job",
        subject_id="job_test",
    )

    assert result.status == ModerationStatus.NEEDS_REVIEW
    assert result.categories_json == {"categories": ["sensitive_content"]}
    assert result.reason_code == "SENSITIVE_CONTENT"


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

    forbidden = (
        "reserve",
        "capture",
        "release",
        "publish",
        "tombstone",
        "trash",
        "untrash",
        "purge",
        "grant",
        "adjust",
    )
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
    assert len(trace) == len(router.build_catalog(db))
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
    assert scored.success_rate == router.CONSERVATIVE_PRIOR_SUCCESS_RATE


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
    catalogue_cost = router.build_catalog(db)["fake_open_workflow"].unit_cost_minor
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


def test_cost_bias_reaches_the_agent_as_context_only(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`classify()`'s request-level cost signal rides along with
    `select_provider`'s candidates as context — never a coefficient
    `route()` applies itself."""
    captured: list[str] = []
    real_run_agent = intent_router.run_agent

    def capture(session, **kwargs):  # type: ignore[no-untyped-def]
        captured.append(kwargs["user_prompt"])
        return real_run_agent(session, **kwargs)

    monkeypatch.setattr(intent_router, "run_agent", capture)

    decision = router.route(
        db,
        operation=Operation.TEXT_TO_IMAGE,
        quality_tier=QualityTier.STANDARD,
        cost_bias=0.9,
    )
    assert decision.selected is not None
    assert json.loads(captured[0])["cost_bias"] == 0.9


def test_cost_bias_is_omitted_from_the_payload_when_the_caller_has_none(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: list[str] = []
    real_run_agent = intent_router.run_agent

    def capture(session, **kwargs):  # type: ignore[no-untyped-def]
        captured.append(kwargs["user_prompt"])
        return real_run_agent(session, **kwargs)

    monkeypatch.setattr(intent_router, "run_agent", capture)

    router.route(db, operation=Operation.TEXT_TO_IMAGE, quality_tier=QualityTier.STANDARD)
    assert "cost_bias" not in json.loads(captured[0])


def test_classify_flags_a_short_but_action_heavy_video_prompt_as_more_complex(
    db: Session,
) -> None:
    """A short prompt naming a multi-subject fight is not `simple` just
    because the text is short — motion/action content drives video
    complexity, not word count (the video-specific dimension in
    `classify()`'s prompt, mirrored deterministically by the stub)."""
    outcome = intent_router.classify(
        db,
        intent="生成一段香港街头斗殴的动态视频，确保动作连贯、场景真实",
        operation=Operation.TEXT_TO_VIDEO.value,
        requested_tier=QualityTier.STANDARD.value,
    )
    assert outcome.data["complexity"] == "complex"


def test_classify_does_not_inflate_complexity_for_a_plain_video_prompt(db: Session) -> None:
    outcome = intent_router.classify(
        db,
        intent="拍一段海边日落的延时视频",
        operation=Operation.TEXT_TO_VIDEO.value,
        requested_tier=QualityTier.STANDARD.value,
    )
    assert outcome.data["complexity"] == "moderate"


def test_the_default_graph_uses_only_registered_node_types(db: Session) -> None:
    """A node type in the seed graph that engineering forgot to register
    would otherwise only surface as a runtime crash on the first real job."""
    graph = default_graph(db)
    types = {n["type"] for n in graph["nodes"]}
    assert types <= set(registry.NODE_TYPES)


def test_the_default_graph_passes_structural_validation(db: Session) -> None:
    """The graph every `Operation` is seeded with must itself satisfy the
    same publish-time checks an admin's custom graph is held to."""
    graph = WorkflowGraph.from_dict(default_graph(db))
    ports = {node_type: spec.output_ports for node_type, spec in registry.NODE_TYPES.items()}
    assert validate_graph(graph, output_ports_by_type=ports) == []


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
        AgentName.PLANNER.value: {"default", planner.CLARIFY_SLOT},
        AgentName.QUALITY.value: {"default"},
        AgentName.COPY.value: {
            copywriter.SUGGEST_SLOT,
            copywriter.ENHANCE_SLOT,
            copywriter.CLARIFY_SLOT,
        },
        AgentName.INTENT_ROUTER.value: {
            intent_router.CLASSIFY_SLOT,
            intent_router.SELECT_PROVIDER_SLOT,
        },
        AgentName.EDITOR_PLANNER.value: {editor_planner.SLOT},
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
                    "models": ["pinned-model", "backup-model"],
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
        model="pinned-model",
    )

    binding = agent_base.effective_binding(db, AgentName.SAFETY.value, profile)
    assert binding.preferred_endpoint_ids == ("pinned-ep", "backup-ep")
    # The model is selected together with the provider and validated against
    # both the default and backup endpoint.
    assert binding.model == "pinned-model"


def test_pinning_an_endpoint_restricts_the_provider_pool(db: Session) -> None:
    """A manual provider binding is authoritative, not a soft preference."""
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
    ] == ["backup-ep"]


def test_a_profile_bound_to_a_known_model_gets_fixed_sampling_params(db: Session) -> None:
    """max_tokens/temperature are no longer typed in by hand — they follow
    whichever model was picked (`app.llm.model_defaults`), same as an agent's
    other properties follow its role."""
    _seeded(db)
    profile = agent_skills_service.create_profile(
        db,
        role="safety",
        key="hot",
        display_name="高温版",
        model="kimi-k3",
        reasoning_model=True,
    )
    assert (profile.max_tokens, profile.temperature_milli) == (2048, 300)

    binding = agent_base.effective_binding(db, AgentName.SAFETY.value, profile)
    assert (binding.max_tokens, binding.temperature, binding.reasoning_model) == (2048, 0.3, True)
    assert binding.preferred_endpoint_ids == ()


def test_debug_chat_uses_the_draft_override_and_records_a_jobless_agent_run(
    db: Session,
) -> None:
    """The whole point of the debug endpoint: an unpublished draft can be
    tried against a real (here, stubbed) model, and the attempt still shows
    up in the agent's usage history despite backing no job."""
    _seeded(db)
    default = agent_skills_service.default_profile(db, "safety")
    assert default is not None

    outcome = agent_base.run_agent_debug(
        db,
        profile=default,
        slot=agent_slots.DEFAULT_SLOT,
        prompt_override="DRAFT_SAFETY_PROMPT",
        history=[{"role": "user", "content": "画面里有血腥场景"}],
    )

    assert outcome.parsed_json == {
        "decision": "needs_review",
        "categories": ["sensitive_content"],
        "reason_code": "SENSITIVE_CONTENT",
        "public_message": "内容需要人工复核，稍后会通知你结果。",
    }
    assert outcome.degraded is False

    run = db.get(AgentRun, outcome.agent_run_id)
    assert run is not None
    assert run.job_id is None
    assert run.agent_profile_id == default.id
    assert run.prompt_slot == agent_slots.DEFAULT_SLOT


def test_an_unregistered_model_leaves_sampling_params_unset(db: Session) -> None:
    """A model this table has never heard of behaves exactly like an unset
    override always did: inherit whatever the role's default agent runs
    with."""
    _seeded(db)
    default = agent_skills_service.default_profile(db, "safety")
    assert default is not None
    agent_skills_service.update_profile(db, default.id, model="kimi-k3", reasoning_model=True)

    variant = agent_skills_service.create_profile(
        db,
        role="safety",
        key="temporary-override",
        display_name="临时覆盖版",
        model="some-unlisted-model",
        reasoning_model=False,
    )
    assert (variant.max_tokens, variant.temperature_milli) == (None, None)

    binding = agent_base.effective_binding(db, AgentName.SAFETY.value, variant)
    assert (binding.max_tokens, binding.temperature) == (2048, 0.3)
    assert binding.reasoning_model is False


def test_pinning_an_endpoint_that_no_longer_exists_does_not_change_provider(db: Session) -> None:
    """A dangling manual binding fails closed instead of changing supplier."""
    from app.llm import failover

    _seeded(db)
    _seed_general_endpoints(db)
    profile = agent_skills_service.create_profile(
        db, role="safety", key="stale", display_name="悬空版", default_endpoint_id="pinned-ep"
    )
    config_service.set_value(
        db, "llm_providers", {"endpoints": {}}, actor_user_id=None, note="删除端点"
    )

    binding = agent_base.effective_binding(db, AgentName.SAFETY.value, profile)
    assert binding.preferred_endpoint_ids == ("pinned-ep",)
    config = config_service.get_typed(db, "llm_providers", LlmProviderConfig)
    assert (
        failover.eligible_candidates(
            config, preferred_ids=binding.preferred_endpoint_ids, model=binding.model
        )
        == []
    )


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
