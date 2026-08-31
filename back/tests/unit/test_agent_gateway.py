"""Agent gateway: tool whitelist, LLM-selected routing and workflow shape."""

from __future__ import annotations

import json

import pytest
from sqlalchemy.orm import Session

from app.agents import base as agent_base
from app.agents import copywriter, editor_planner, intent_router, planner, router, tools
from app.agents import slots as agent_slots
from app.domain.agent_skills import service as agent_skills_service
from app.domain.errors import ProviderTemporaryFailure, ValidationFailed
from app.models import AgentRun, ProviderStat, User
from app.models.enums import AgentName, Operation, QualityTier
from app.platform_config import service as config_service
from app.platform_config.schemas import LlmProviderConfig
from app.workflows import describe_workflow, registry
from app.workflows.defaults import default_graph
from app.workflows.graph import WorkflowGraph
from app.workflows.graph import validate as validate_graph
from tests.fake_provider_catalog import build_fake_catalog
from tests.llm_catalog import bind_default_agents_to_catalog


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
    bind_default_agents_to_catalog(db)
    first = router.route(db, operation=Operation.TEXT_TO_IMAGE, quality_tier=QualityTier.STANDARD)
    second = router.route(db, operation=Operation.TEXT_TO_IMAGE, quality_tier=QualityTier.STANDARD)
    assert first.selected is not None
    assert first.selected.provider == second.selected.provider
    assert first.reason == second.reason


def test_every_candidate_records_why_it_was_rejected(db: Session) -> None:
    """An operator replaying a decision needs a reason for each loser, not just
    the name of the winner."""
    bind_default_agents_to_catalog(db)
    decision = router.route(
        db, operation=Operation.TEXT_TO_VIDEO, quality_tier=QualityTier.CINEMATIC
    )
    trace = decision.trace()
    assert len(trace) == len(router.build_catalog(db))
    for entry in trace:
        if not entry["eligible"]:
            assert entry["filter_reason"]


def test_a_route_that_cannot_do_the_operation_is_filtered_not_scored(db: Session) -> None:
    bind_default_agents_to_catalog(db)
    decision = router.route(
        db, operation=Operation.TEXT_TO_VIDEO, quality_tier=QualityTier.STANDARD
    )
    open_workflow = next(c for c in decision.candidates if c.provider == "fake_open_workflow")
    assert open_workflow.eligible is False
    assert open_workflow.filter_reason == "operation_not_supported"
    assert open_workflow.effective_cost_micro_usd == 0


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

    bind_default_agents_to_catalog(db)
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

    bind_default_agents_to_catalog(db)
    decision = router.route(
        db, operation=Operation.TEXT_TO_IMAGE, quality_tier=QualityTier.STANDARD
    )
    flaky = next(c for c in decision.candidates if c.provider == "fake_open_workflow")
    catalogue_cost = router.build_catalog(db)["fake_open_workflow"].unit_cost_micro_usd
    assert flaky.effective_cost_micro_usd > catalogue_cost


def test_llm_picks_the_lowest_effective_cost_among_eligible_candidates(db: Session) -> None:
    """Deterministic stub selection: cheapest-effective-cost eligible route
    wins, and the reason trail says an LLM made the call."""
    bind_default_agents_to_catalog(db)
    decision = router.route(
        db, operation=Operation.TEXT_TO_IMAGE, quality_tier=QualityTier.STANDARD
    )
    assert decision.selected is not None
    eligible = [c for c in decision.candidates if c.eligible]
    cheapest = min(eligible, key=lambda c: (c.effective_cost_micro_usd, c.provider))
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

    bind_default_agents_to_catalog(db)
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

    bind_default_agents_to_catalog(db)
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


def test_default_for_asset_kind_is_rejected_outside_the_copy_role(db: Session) -> None:
    """Only "AI 润色" (the `copy` role) routes by `ImageAssetKind` — a judgment
    role has no notion of a character/scene/cover asset to specialise for."""
    _seeded(db)
    with pytest.raises(ValidationFailed):
        agent_skills_service.create_profile(
            db,
            role="safety",
            key="video-strict",
            display_name="严格版",
            default_for_asset_kind="character",
        )


def test_default_for_asset_kind_rejects_a_kind_outside_the_three_buckets(db: Session) -> None:
    """`general` is deliberately not a bucket: a plain image job keeps using
    the role's ordinary default agent, never a kind-specific one."""
    _seeded(db)
    with pytest.raises(ValidationFailed):
        agent_skills_service.create_profile(
            db,
            role="copy",
            key="enhance-general",
            display_name="通用润色",
            default_for_asset_kind="general",
        )


def test_the_copy_request_bucket_is_assignable(db: Session) -> None:
    """`copy` is the catch-all routing key for non-asset polish / suggest /
    script — it is assignable even though it is not an ImageAssetKind."""
    _seeded(db)
    profile = agent_skills_service.create_profile(
        db,
        role="copy",
        key="copy-catch-all",
        display_name="文案生成",
        default_for_asset_kind="copy",
    )
    assert profile.default_for_asset_kind == "copy"
    assert agent_skills_service.default_profile_for_asset_kind(db, "copy", "copy").id == profile.id


def test_promoting_a_second_asset_kind_default_demotes_the_first(db: Session) -> None:
    """Mirrors `is_default`: at most one profile per `(role, bucket)`."""
    _seeded(db)
    first = agent_skills_service.create_profile(
        db,
        role="copy",
        key="enhance-character-a",
        display_name="角色润色 A",
        default_for_asset_kind="character",
    )
    assert first.default_for_asset_kind == "character"

    second = agent_skills_service.create_profile(
        db,
        role="copy",
        key="enhance-character-b",
        display_name="角色润色 B",
        default_for_asset_kind="character",
    )
    db.refresh(first)
    assert first.default_for_asset_kind is None
    assert second.default_for_asset_kind == "character"
    assert (
        agent_skills_service.default_profile_for_asset_kind(db, "copy", "character").id == second.id
    )


def test_update_profile_can_explicitly_clear_the_asset_kind_default(db: Session) -> None:
    """Unlike `is_default`, clearing this one directly is allowed — there is
    no invariant requiring some profile always hold a given bucket."""
    _seeded(db)
    profile = agent_skills_service.create_profile(
        db,
        role="copy",
        key="enhance-scene",
        display_name="场景润色",
        default_for_asset_kind="scene",
    )
    agent_skills_service.update_profile(db, profile.id, default_for_asset_kind=None)
    db.refresh(profile)
    assert profile.default_for_asset_kind is None
    assert agent_skills_service.default_profile_for_asset_kind(db, "copy", "scene") is None


def test_update_profile_leaves_the_asset_kind_default_untouched_when_omitted(
    db: Session,
) -> None:
    """The sentinel default (`UNSET_BINDING`) must behave like `reasoning_model`'s
    — an update that does not mention the field must not silently clear it."""
    _seeded(db)
    profile = agent_skills_service.create_profile(
        db,
        role="copy",
        key="enhance-cover",
        display_name="封面润色",
        default_for_asset_kind="cover",
    )
    agent_skills_service.update_profile(db, profile.id, display_name="封面润色 · 改名")
    db.refresh(profile)
    assert profile.default_for_asset_kind == "cover"


def test_default_profile_for_asset_kind_is_none_for_an_unclaimed_bucket(db: Session) -> None:
    _seeded(db)
    assert agent_skills_service.default_profile_for_asset_kind(db, "copy", "cover") is None
    # An unrecognised kind (e.g. `general`, or empty) never resolves either,
    # regardless of what happens to be configured.
    assert agent_skills_service.default_profile_for_asset_kind(db, "copy", "general") is None
    assert agent_skills_service.default_profile_for_asset_kind(db, "copy", "") is None


def test_ensure_default_enhance_asset_agents_is_idempotent(db: Session) -> None:
    """Mirrors `ensure_default_profiles`'s own idempotency test: safe to call
    on every startup, and an operator's later edit is not clobbered."""
    from app.scripts import seed as seed_script

    _seeded(db)
    seed_script.ensure_default_enhance_asset_agents(db)

    buckets = {"character", "scene", "cover"}
    profiles_by_bucket = {
        bucket: agent_skills_service.default_profile_for_asset_kind(db, "copy", bucket)
        for bucket in buckets
    }
    assert all(profile is not None for profile in profiles_by_bucket.values())
    assert len({profile.id for profile in profiles_by_bucket.values()}) == 3

    # An operator demotes one and repoints it manually; a second run must not
    # re-seed the bucket out from under that choice.
    character_profile = profiles_by_bucket["character"]
    assert character_profile is not None
    agent_skills_service.update_profile(db, character_profile.id, default_for_asset_kind=None)

    seed_script.ensure_default_enhance_asset_agents(db)
    db.refresh(character_profile)
    assert character_profile.default_for_asset_kind is None
    assert agent_skills_service.default_profile_for_asset_kind(db, "copy", "character") is None


def test_ensure_default_copy_request_agent_marks_the_role_default(db: Session) -> None:
    from app.scripts import seed as seed_script

    _seeded(db)
    seed_script.ensure_default_copy_request_agent(db)
    default = agent_skills_service.default_profile(db, "copy")
    assert default is not None
    assert default.default_for_asset_kind == "copy"
    first_id = default.id

    seed_script.ensure_default_copy_request_agent(db)
    db.refresh(default)
    assert default.default_for_asset_kind == "copy"
    assert default.id == first_id

    other = agent_skills_service.create_profile(
        db, role="copy", key="copy-repointed", display_name="另挂", default_for_asset_kind="copy"
    )
    db.refresh(default)
    assert default.default_for_asset_kind is None
    seed_script.ensure_default_copy_request_agent(db)
    db.refresh(default)
    db.refresh(other)
    assert other.default_for_asset_kind == "copy"
    assert default.default_for_asset_kind is None


def test_seed_syncs_factory_copy_prompts_onto_the_seeded_agents(db: Session) -> None:
    """Runtime resolve prefers the published row, so a rewritten module
    constant is invisible until the seeded agents' active drafts move."""
    from app.scripts import seed as seed_script

    _seeded(db)
    seed_script.ensure_default_copy_request_agent(db)
    seed_script.ensure_default_enhance_asset_agents(db)

    copy_default = agent_skills_service.default_profile(db, "copy")
    assert copy_default is not None
    character = agent_skills_service.find_profile(db, "copy", "enhance-character")
    scene = agent_skills_service.find_profile(db, "copy", "enhance-scene")
    cover = agent_skills_service.find_profile(db, "copy", "enhance-cover")
    assert character is not None and scene is not None and cover is not None

    agent_skills_service.publish(
        db,
        profile_id=copy_default.id,
        slot=copywriter.SUGGEST_SLOT,
        prompt_template="你是造浪平台的文案助手。旧的作品文案稿。",
        tool_grants=[],
        actor_user_id=None,
        reason="old factory",
    )
    agent_skills_service.publish(
        db,
        profile_id=character.id,
        slot=copywriter.ENHANCE_SLOT,
        prompt_template="你是造浪平台的提示词教练。旧的角色润色稿。",
        tool_grants=[],
        actor_user_id=None,
        reason="old factory",
    )
    agent_skills_service.update_profile(
        db,
        character.id,
        description="角色资产的画面描述润色，额外关注人物一致性与表情神态，并要求全身入镜、纯色背景。",
    )
    agent_skills_service.publish(
        db,
        profile_id=scene.id,
        slot=copywriter.ENHANCE_SLOT,
        prompt_template="你是运营自己写的场景润色提示词，不要覆盖。",
        tool_grants=[],
        actor_user_id=None,
        reason="operator edit",
    )
    cover_before = agent_skills_service.get_active_prompt(
        db, "copy", "FALLBACK", agent_id=cover.id, slot=copywriter.ENHANCE_SLOT
    )

    seed_script.sync_seeded_copy_agent_prompts(db)

    suggest, _ = agent_skills_service.get_active_prompt(
        db, "copy", "FALLBACK", agent_id=copy_default.id, slot=copywriter.SUGGEST_SLOT
    )
    character_prompt, _ = agent_skills_service.get_active_prompt(
        db, "copy", "FALLBACK", agent_id=character.id, slot=copywriter.ENHANCE_SLOT
    )
    scene_prompt, _ = agent_skills_service.get_active_prompt(
        db, "copy", "FALLBACK", agent_id=scene.id, slot=copywriter.ENHANCE_SLOT
    )
    cover_after = agent_skills_service.get_active_prompt(
        db, "copy", "FALLBACK", agent_id=cover.id, slot=copywriter.ENHANCE_SLOT
    )
    assert suggest == copywriter.SYSTEM_PROMPT
    assert character_prompt == copywriter.ENHANCE_SYSTEM_PROMPT_CHARACTER
    assert scene_prompt == "你是运营自己写的场景润色提示词，不要覆盖。"
    assert cover_after == cover_before
    db.refresh(character)
    assert character.description == (
        "角色立绘教练：把同一个人写到能进库、出三视图，强制全身入镜与纯色背景。"
    )


def test_seed_does_not_republish_when_factory_copy_prompts_are_current(db: Session) -> None:
    from app.scripts import seed as seed_script

    _seeded(db)
    seed_script.ensure_default_enhance_asset_agents(db)
    character = agent_skills_service.find_profile(db, "copy", "enhance-character")
    assert character is not None
    versions_before = agent_skills_service.list_versions(
        db, profile_id=character.id, slot=copywriter.ENHANCE_SLOT
    )
    seed_script.sync_seeded_copy_agent_prompts(db)
    versions_after = agent_skills_service.list_versions(
        db, profile_id=character.id, slot=copywriter.ENHANCE_SLOT
    )
    assert [row.version for row in versions_after] == [row.version for row in versions_before]
    prompt, _ = agent_skills_service.get_active_prompt(
        db, "copy", "FALLBACK", agent_id=character.id, slot=copywriter.ENHANCE_SLOT
    )
    assert prompt == copywriter.ENHANCE_SYSTEM_PROMPT_CHARACTER


def test_resolve_copy_agent_id_prefers_asset_kind_then_the_copy_bucket(db: Session) -> None:
    _seeded(db)
    character = agent_skills_service.create_profile(
        db,
        role="copy",
        key="enhance-character",
        display_name="角色",
        default_for_asset_kind="character",
    )
    catch_all = agent_skills_service.create_profile(
        db, role="copy", key="copy-all", display_name="文案", default_for_asset_kind="copy"
    )
    other = agent_skills_service.create_profile(db, role="copy", key="pinned", display_name="钉死")

    assert (
        agent_skills_service.resolve_copy_agent_id(db, asset_kind="character") == character.id
    )
    assert agent_skills_service.resolve_copy_agent_id(db, asset_kind="general") == catch_all.id
    assert agent_skills_service.resolve_copy_agent_id(db, asset_kind="") == catch_all.id
    assert (
        agent_skills_service.resolve_copy_agent_id(db, asset_kind="character", agent_id=other.id)
        == other.id
    )


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


def test_planner_clarify_prompt_never_asks_about_form_fixed_or_reference_known_params() -> None:
    """时长/分辨率/画面比例在提交创作时已经是表单必填的结构化参数
    （`back/app/api/schemas/jobs.py`），clarify 运行时永远不会真的缺失。
    参考素材上的主体/背景同样已知。防止提示词回退到把这些当作可追问类别。
    """
    prompt = planner.CLARIFY_SYSTEM_PROMPT
    assert "时长（视频时）" not in prompt
    for keyword in ("时长", "分辨率", "画面比例"):
        assert keyword in prompt
    assert "has_reference_material" in prompt
    for keyword in ("主体", "背景"):
        assert keyword in prompt


def test_every_prompt_slot_is_reachable_from_some_agent_call() -> None:
    """A declared slot with no caller is an editor tab that changes nothing;
    a caller using an undeclared slot cannot be edited at all."""
    called = {
        AgentName.SAFETY.value: {"default"},
        AgentName.PLANNER.value: {
            "default",
            planner.CLARIFY_SLOT,
            planner.ASSET_PLAN_SLOT,
            planner.VIDEO_ASSET_PLAN_SLOT,
        },
        AgentName.QUALITY.value: {"default"},
        AgentName.COPY.value: {
            copywriter.SUGGEST_SLOT,
            copywriter.ENHANCE_SLOT,
            copywriter.CLARIFY_SLOT,
            copywriter.SCRIPT_DRAFT_SLOT,
            copywriter.SCRIPT_REVISE_SLOT,
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
                    "model": "pinned-model",
                    "role": "primary",
                },
                "backup-ep": {
                    "name": "备用端点",
                    "base_url": "https://backup.invalid",
                    "api_key": "k",
                    "kind": "general",
                    # Deliberately a different model: a backup exists to keep
                    # serving when the default is down, not to mirror its name.
                    "model": "backup-model",
                    "role": "backup",
                },
            }
        },
        actor_user_id=None,
        note="test bootstrap",
    )


def test_a_variant_that_pins_nothing_still_draws_from_the_shared_pool(db: Session) -> None:
    """The behaviour every variant had before per-variant bindings existed.

    Unpinned means "whatever the pool offers first", so the model comes from
    the primary endpoint rather than being empty.
    """
    _seeded(db)
    _seed_general_endpoints(db)
    profile = agent_skills_service.default_profile(db, "safety")
    assert profile is not None

    binding = agent_base.effective_binding(db, AgentName.SAFETY.value, profile)
    assert binding.preferred_endpoint_ids == ()
    assert binding.model == "pinned-model"


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
    # No model was pinned because none can be: the default endpoint names it.
    assert binding.model == "pinned-model"


def test_a_binding_whose_endpoints_all_vanished_counts_as_unbound(db: Session) -> None:
    """A pin that drifted off the catalog must not borrow the shared pool."""
    _seeded(db)
    _seed_general_endpoints(db)
    profile = agent_skills_service.create_profile(
        db,
        role="safety",
        key="orphaned",
        display_name="失效绑定版",
        default_endpoint_id="pinned-ep",
    )
    config_service.set_value(
        db, "llm_providers", {"endpoints": {}}, actor_user_id=None, note="drop the pool"
    )

    binding = agent_base.effective_binding(db, AgentName.SAFETY.value, profile)
    assert binding.model == ""


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


def test_a_profile_without_sampling_overrides_uses_generic_defaults(db: Session) -> None:
    """Sampling is no longer looked up by model name — unbound numbers use
    the generic fallback in `app.llm.model_defaults`."""
    from app.llm.model_defaults import DEFAULT_MAX_TOKENS, DEFAULT_TEMPERATURE
    from tests.llm_catalog import TEST_LLM_MODEL, seed_test_llm_catalog

    _seeded(db)
    seed_test_llm_catalog(db)
    profile = agent_skills_service.create_profile(
        db,
        role="safety",
        key="hot",
        display_name="高温版",
        reasoning_model=True,
    )
    assert (profile.max_tokens, profile.temperature_milli) == (None, None)

    binding = agent_base.effective_binding(db, AgentName.SAFETY.value, profile)
    assert (binding.max_tokens, binding.temperature, binding.reasoning_model) == (
        DEFAULT_MAX_TOKENS,
        DEFAULT_TEMPERATURE,
        True,
    )
    assert binding.model == TEST_LLM_MODEL
    assert binding.preferred_endpoint_ids == ()


def test_a_profile_without_sampling_overrides_uses_the_model_output_ceiling(
    db: Session,
) -> None:
    from tests.llm_catalog import TEST_LLM_MODEL, seed_test_llm_catalog

    _seeded(db)
    seed_test_llm_catalog(db, max_output_tokens=16_384)
    profile = agent_skills_service.create_profile(
        db,
        role="safety",
        key="model-budget",
        display_name="跟模型走",
    )

    binding = agent_base.effective_binding(db, AgentName.SAFETY.value, profile)
    assert binding.max_tokens == 16_384
    assert binding.model == TEST_LLM_MODEL


def test_a_profile_max_tokens_is_clamped_to_the_model_output_ceiling(db: Session) -> None:
    from tests.llm_catalog import seed_test_llm_catalog

    _seeded(db)
    seed_test_llm_catalog(db, max_output_tokens=4096)
    profile = agent_skills_service.create_profile(
        db,
        role="safety",
        key="over-budget",
        display_name="超模型上限",
    )
    # Admin no longer writes this column; leftover rows still exist and
    # must not ask a 4k model for 20k completion tokens.
    profile.max_tokens = 20_000
    db.flush()

    binding = agent_base.effective_binding(db, AgentName.SAFETY.value, profile)
    assert binding.max_tokens == 4096


def test_run_agent_max_tokens_is_a_floor_the_bound_endpoints_ceiling_can_beat(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A caller-supplied `max_tokens` (a slot's own constant, e.g.
    `copywriter.SCRIPT_MAX_TOKENS`) never shrinks a bound endpoint's own
    larger declared `max_output_tokens` — this is what let a real reasoning
    model get artificially capped down to a small first-attempt budget and
    spend the whole thing on hidden thinking with zero completion tokens.
    See `run_agent`/`run_agent_stream`'s floor semantics in
    `back/app/agents/base.py`."""
    from app.llm import client as llm_client
    from app.llm.normalize import NormalizedResponse
    from tests.llm_catalog import seed_test_llm_catalog

    _seeded(db)
    seed_test_llm_catalog(db, max_output_tokens=16_384)
    seen: dict[str, int] = {}

    def _complete(**kwargs: object) -> llm_client.LlmCallResult:
        seen["max_tokens"] = kwargs["max_tokens"]  # type: ignore[assignment]
        return llm_client.LlmCallResult(
            response=NormalizedResponse(
                text="{}", data={}, finish_reason="stop", prompt_tokens=1, completion_tokens=1
            ),
            latency_ms=1,
        )

    monkeypatch.setattr(llm_client, "complete", _complete)
    agent_base.run_agent(
        db,
        agent_name=AgentName.SAFETY.value,
        system_prompt="{}",
        user_prompt="x",
        fallback={"decision": "needs_review"},
        max_tokens=512,
    )
    assert seen["max_tokens"] == 16_384


def test_run_agent_max_tokens_floor_still_wins_over_a_smaller_endpoint_ceiling(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other direction: an endpoint with a smaller declared ceiling than
    the caller's own floor does not shrink the request either — the floor
    is a minimum, and the endpoint's `output_budget()` (exercised elsewhere,
    see `test_llm_gateway_failover.py`) is what actually clamps the wire
    request against the real ceiling downstream."""
    from app.llm import client as llm_client
    from app.llm.normalize import NormalizedResponse
    from tests.llm_catalog import seed_test_llm_catalog

    _seeded(db)
    seed_test_llm_catalog(db, max_output_tokens=4_096)
    seen: dict[str, int] = {}

    def _complete(**kwargs: object) -> llm_client.LlmCallResult:
        seen["max_tokens"] = kwargs["max_tokens"]  # type: ignore[assignment]
        return llm_client.LlmCallResult(
            response=NormalizedResponse(
                text="{}", data={}, finish_reason="stop", prompt_tokens=1, completion_tokens=1
            ),
            latency_ms=1,
        )

    monkeypatch.setattr(llm_client, "complete", _complete)
    agent_base.run_agent(
        db,
        agent_name=AgentName.SAFETY.value,
        system_prompt="{}",
        user_prompt="x",
        fallback={"decision": "needs_review"},
        max_tokens=8_192,
    )
    assert seen["max_tokens"] == 8_192


def test_debug_chat_uses_the_draft_override_and_records_a_jobless_agent_run(
    db: Session,
) -> None:
    """The whole point of the debug endpoint: an unpublished draft can be
    tried against a real (here, stubbed) model, and the attempt still shows
    up in the agent's usage history despite backing no job."""
    from tests.llm_catalog import bind_default_agents_to_catalog

    bind_default_agents_to_catalog(db)
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


def test_run_agent_persists_thinking_outside_output_json(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reasoning tokens stay on `AgentRun.thinking_text` so JSON replay is
    still a structured payload, not a think-block dump."""
    from app.llm import client as llm_client
    from app.llm.normalize import NormalizedResponse
    from tests.llm_catalog import bind_default_agents_to_catalog

    bind_default_agents_to_catalog(db)
    payload = {
        "decision": "approve",
        "categories": [],
        "reason_code": "OK",
        "public_message": "",
    }

    def _complete(**kwargs: object) -> llm_client.LlmCallResult:
        on_chunk = kwargs.get("on_chunk")
        if callable(on_chunk):
            on_chunk(llm_client.StreamChunk(kind="thinking", text="先判断尺度"))
        return llm_client.LlmCallResult(
            response=NormalizedResponse(
                text=json.dumps(payload, ensure_ascii=False),
                data=payload,
                finish_reason="stop",
                prompt_tokens=4,
                completion_tokens=4,
                model="test-llm",
            ),
            latency_ms=8,
            thinking="先判断尺度",
        )

    monkeypatch.setattr(llm_client, "complete", _complete)
    outcome = agent_base.run_agent(
        db,
        agent_name=AgentName.SAFETY.value,
        system_prompt="{}",
        user_prompt="一只猫",
        fallback={"decision": "needs_review"},
    )
    run = db.get(AgentRun, outcome.agent_run_id)
    assert run is not None
    assert run.thinking_text == "先判断尺度"
    assert outcome.thinking == "先判断尺度"
    assert "先判断尺度" not in json.dumps(run.output_json, ensure_ascii=False)


def test_debug_chat_with_unparseable_output_is_recorded_as_degraded(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The debug-chat endpoint exists so an operator can see whether a draft
    prompt actually produces valid JSON before publishing it — reporting
    `degraded=False` on a response nothing could parse would hide exactly the
    failure this tool exists to surface (see `run_agent`'s own handling of
    the same case in `test_an_unparseable_response_is_recorded_as_a_failed_
    degraded_run`)."""
    from app.llm import client as llm_client
    from app.models.enums import AgentRunStatus

    bind_default_agents_to_catalog(db)
    default = agent_skills_service.default_profile(db, "safety")
    assert default is not None

    class _Unparseable:
        data = None
        text = "抱歉，我无法回答。"
        model = "test-llm"
        prompt_tokens = 10
        completion_tokens = 5
        truncated = False

    monkeypatch.setattr(
        llm_client,
        "complete",
        lambda **_: llm_client.LlmCallResult(response=_Unparseable(), latency_ms=12),  # type: ignore[arg-type]
    )

    outcome = agent_base.run_agent_debug(
        db,
        profile=default,
        slot=agent_slots.DEFAULT_SLOT,
        prompt_override="DRAFT_SAFETY_PROMPT",
        history=[{"role": "user", "content": "画面里有血腥场景"}],
    )

    assert outcome.parsed_json is None
    assert outcome.degraded is True

    run = db.get(AgentRun, outcome.agent_run_id)
    assert run is not None
    assert run.status == AgentRunStatus.FAILED
    assert run.degraded is True
    assert run.degrade_reason == "json_parse_failed"


@pytest.mark.real_gateway_seams
def test_an_unbound_agent_raises_instead_of_calling_a_vendor(db: Session) -> None:
    """No catalog model on the profile means no invented name, no HTTP and no
    silent fallback — the caller must see the outage immediately.

    Opts out of the autouse fake gateway (`@pytest.mark.real_gateway_seams`):
    the fake stays permissive about unbound models like `app.llm.stub` always
    was, so this needs the real `app.llm.client.complete` to observe the
    actual production rule."""
    _seeded(db)
    default = agent_skills_service.default_profile(db, "safety")
    binding = agent_base.effective_binding(db, AgentName.SAFETY.value, default)
    assert binding.model == ""

    with pytest.raises(ProviderTemporaryFailure):
        agent_base.run_agent(
            db,
            agent_name=AgentName.SAFETY.value,
            system_prompt="{}",
            user_prompt="x",
            fallback={"decision": "needs_review"},
        )
    assert db.query(AgentRun).filter(AgentRun.agent_name == AgentName.SAFETY.value).count() == 0


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
    assert failover.eligible_candidates(config, preferred_ids=binding.preferred_endpoint_ids) == []


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
