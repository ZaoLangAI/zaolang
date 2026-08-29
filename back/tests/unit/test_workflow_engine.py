"""Workflow engine building blocks: graph validation, the node type registry,
and `execute_join`'s aggregation logic — everything that does not need a real
job/session to exercise (see `tests/integration/test_workflow_parallel_execution.py`
for the fan-out/join end-to-end behaviour, and
`tests/integration/test_generation_lifecycle.py` for the runner's equivalence
with the retired hardcoded pipeline).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.credits import service as credits_service
from app.domain.jobs import input_requests
from app.domain.jobs import service as jobs_service
from app.domain.jobs import state_machine as sm
from app.models import AgentRun, GenerationJob, JobEvent, User
from app.models.base import new_id
from app.models.enums import (
    CharacterViewAngle,
    ImageAssetKind,
    JobEventType,
    JobOrigin,
    JobStatus,
    Operation,
    QualityTier,
    VideoAssetKind,
)
from app.realtime import publisher
from app.workflows import registry
from app.workflows.configs import (
    JoinConfig,
    PlanningConfig,
    ProviderGenerateConfig,
    RouteScoreConfig,
)
from app.workflows.defaults import asset_graph, default_graph
from app.workflows.graph import WorkflowGraph
from app.workflows.graph import validate as validate_graph
from app.workflows.nodes import (
    execute_join,
    execute_planning,
    execute_provider_generate,
    execute_route_score,
)
from app.workflows.runner import WorkflowRunner
from app.workflows.types import NodeResult, WorkflowContext
from tests.fake_llm_gateway import PLANNER_CLARIFY_MARKER

_OUTPUT_PORTS_BY_TYPE = {
    node_type: spec.output_ports for node_type, spec in registry.NODE_TYPES.items()
}


def _validate(graph_dict: dict) -> list[str]:
    return validate_graph(
        WorkflowGraph.from_dict(graph_dict), output_ports_by_type=_OUTPUT_PORTS_BY_TYPE
    )


def test_the_seeded_default_graph_is_valid_for_every_registered_node_type(db: Session) -> None:
    """The one graph every `Operation` actually ships with must always pass
    its own validator — a regression here would brick every new job."""
    errors = _validate(default_graph(db))
    assert errors == []


def test_an_empty_graph_is_rejected() -> None:
    assert _validate({"nodes": [], "edges": []}) == ["图不能为空。"]


def test_an_unknown_node_type_is_rejected() -> None:
    errors = _validate(
        {
            "nodes": [{"id": "n1", "type": "not_a_real_node_type", "config": {}}],
            "edges": [],
        }
    )
    assert any("未知节点类型" in e for e in errors)


def test_duplicate_node_ids_are_rejected() -> None:
    errors = _validate(
        {
            "nodes": [
                {"id": "n1", "type": "safety_check", "config": {}},
                {"id": "n1", "type": "fail", "config": {}},
            ],
            "edges": [{"from": "n1", "from_port": "pass", "to": "n1"}],
        }
    )
    assert any("重复" in e for e in errors)


def test_an_edge_pointing_at_a_nonexistent_node_is_rejected() -> None:
    errors = _validate(
        {
            "nodes": [{"id": "n1", "type": "safety_check", "config": {}}],
            "edges": [{"from": "n1", "from_port": "pass", "to": "ghost"}],
        }
    )
    assert any("不存在的终点节点" in e for e in errors)


def test_a_graph_with_more_than_one_entry_node_is_rejected() -> None:
    """Two nodes with no incoming edge means the runner would not know where
    to start; `_entry_node_id` also assumes exactly one."""
    errors = _validate(
        {
            "nodes": [
                {"id": "a", "type": "safety_check", "config": {}},
                {"id": "b", "type": "fail", "config": {}},
            ],
            "edges": [],
        }
    )
    assert any("入口节点" in e for e in errors)


def test_an_orphan_node_unreachable_from_the_entry_is_rejected() -> None:
    errors = _validate(
        {
            "nodes": [
                {"id": "entry", "type": "safety_check", "config": {}},
                {"id": "orphan", "type": "fail", "config": {}},
            ],
            "edges": [{"from": "entry", "from_port": "pass", "to": "entry"}],
        }
    )
    # `entry` also can't reach a terminal here, but the orphan check must
    # independently flag `orphan` too.
    assert any("孤立节点" in e for e in errors)


def test_a_node_with_no_path_to_a_terminal_state_is_rejected() -> None:
    """Every non-terminal node must be able to reach `settle_success`/`fail`
    — this is the invariant that stops an admin from publishing a graph that
    would strand a job's reserved credits forever."""
    errors = _validate(
        {
            "nodes": [
                {"id": "entry", "type": "safety_check", "config": {}},
                {"id": "stuck", "type": "planning", "config": {}},
            ],
            "edges": [
                {"from": "entry", "from_port": "pass", "to": "stuck"},
                {"from": "entry", "from_port": "reject", "to": "stuck"},
                {"from": "stuck", "from_port": "ok", "to": "stuck"},
            ],
        }
    )
    assert any("没有任何路径可以到达终态节点" in e for e in errors)


def test_an_output_port_with_no_outgoing_edge_is_rejected(db: Session) -> None:
    """The mistake that used to publish cleanly and then fail live jobs.

    `_walk` raises `WORKFLOW_MISCONFIGURED` when it needs an edge off the
    port a node just returned and finds none — the job fails and is refunded.
    Forgetting one branch must therefore be caught at publish time.
    """
    graph = default_graph(db)
    graph["edges"] = [e for e in graph["edges"] if e["from_port"] != "retry"]
    errors = _validate(graph)
    assert any("输出端口 retry 没有连线" in e for e in errors)


def test_an_edge_leaving_a_port_the_node_type_does_not_declare_is_rejected(db: Session) -> None:
    """Only reachable by hand-editing the JSON or retyping a node — the
    canvas draws its handles from the same port table — but such an edge can
    never be selected, so whatever it leads to is silently dead."""
    graph = default_graph(db)
    graph["edges"].append(
        {"id": "bogus", "from": "planning", "from_port": "definitely_not_a_port", "to": "fail"}
    )
    errors = _validate(graph)
    assert any("没有名为 definitely_not_a_port 的输出端口" in e for e in errors)


def test_a_second_sequential_edge_off_one_port_is_rejected(db: Session) -> None:
    """`_walk` takes `edges[0]`, so the second edge is drawn on the canvas
    but never executed — the graph an operator sees would not be the graph
    that runs. Parallel edges are exempt; fan-out is exactly what they mean."""
    graph = default_graph(db)
    graph["edges"].append({"id": "second", "from": "planning", "from_port": "ok", "to": "fail"})
    errors = _validate(graph)
    assert any("有 2 条非并行连线" in e for e in errors)


def test_a_lone_parallel_edge_without_a_sibling_branch_is_rejected() -> None:
    errors = _validate(
        {
            "nodes": [
                {"id": "entry", "type": "safety_check", "config": {}},
                {"id": "a", "type": "fail", "config": {}},
            ],
            "edges": [
                {"from": "entry", "from_port": "pass", "to": "a", "kind": "parallel"},
                {"from": "entry", "from_port": "reject", "to": "a"},
            ],
        }
    )
    assert any("只有一条并行分支" in e for e in errors)


def test_parallel_branches_that_converge_on_different_joins_are_rejected() -> None:
    errors = _validate(
        {
            "nodes": [
                {"id": "entry", "type": "safety_check", "config": {}},
                {"id": "a", "type": "fail", "config": {}},
                {"id": "join1", "type": "join", "config": {}},
                {"id": "join2", "type": "join", "config": {}},
                {"id": "b", "type": "fail", "config": {}},
            ],
            "edges": [
                {"from": "entry", "from_port": "pass", "to": "join1", "kind": "parallel"},
                {"from": "entry", "from_port": "pass", "to": "join2", "kind": "parallel"},
                {"from": "entry", "from_port": "reject", "to": "a"},
                {"from": "join1", "from_port": "ok", "to": "b"},
                {"from": "join2", "from_port": "ok", "to": "b"},
            ],
        }
    )
    assert any("必须汇合到同一个 join 节点" in e for e in errors)


def test_parallel_branches_that_never_reach_any_join_are_rejected() -> None:
    errors = _validate(
        {
            "nodes": [
                {"id": "entry", "type": "safety_check", "config": {}},
                {"id": "a", "type": "fail", "config": {}},
                {"id": "b", "type": "fail", "config": {}},
            ],
            "edges": [
                {"from": "entry", "from_port": "pass", "to": "a", "kind": "parallel"},
                {"from": "entry", "from_port": "pass", "to": "b", "kind": "parallel"},
                {"from": "entry", "from_port": "reject", "to": "a"},
            ],
        }
    )
    assert any("无法到达 join 节点" in e for e in errors)


@pytest.mark.parametrize("node_type", sorted(registry.NODE_TYPES.keys()))
def test_every_node_types_config_schema_rejects_an_unknown_field(node_type: str) -> None:
    """`extra="forbid"` on every `NodeConfig`: a typo'd config key in a
    published graph must fail loudly at publish time, not be silently
    ignored at run time."""
    with pytest.raises(ValidationError):
        registry.parse_config(node_type, {"this_field_does_not_exist": True})


def test_route_score_config_rejects_an_out_of_range_max_attempts() -> None:
    with pytest.raises(ValidationError):
        RouteScoreConfig.model_validate({"max_attempts": 0})
    with pytest.raises(ValidationError):
        RouteScoreConfig.model_validate({"max_attempts": 11})


def test_node_types_all_expose_a_json_schema_for_the_editors_config_panel() -> None:
    """The admin `node-types` endpoint hands this straight to the frontend;
    it must never fail to serialize."""
    for spec in registry.NODE_TYPES.values():
        schema = spec.config_schema.model_json_schema()
        assert isinstance(schema, dict)


def test_route_score_forwards_the_intent_hints_cost_bias_to_the_router(
    db: Session, author: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`execute_intent_router` parks `cost_bias` in `ctx.state["intent_hint"]`;
    `execute_route_score` must read it back and hand it to `router.route` as
    context, not silently drop it on the floor."""
    from app.workflows import nodes as workflow_nodes

    credits_service.grant(db, author.id, 5_000, idempotency_key=new_id("grant"))
    job = jobs_service.submit(
        db,
        user_id=author.id,
        operation=Operation.TEXT_TO_IMAGE,
        quality_tier=QualityTier.STANDARD,
        params={"prompt": "路由 cost_bias 转发", "aspect_ratio": "16:9"},
        idempotency_key=new_id("idk"),
    ).job

    captured: dict[str, object] = {}
    real_route = workflow_nodes.router.route

    def capture(session, **kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        return real_route(session, **kwargs)

    monkeypatch.setattr(workflow_nodes.router, "route", capture)

    params = dict(job.request_json)
    ctx = WorkflowContext(session=db, job=job, prompt=str(params.get("prompt", "")), params=params)
    ctx.state["intent_hint"] = {"cost_bias": 0.7}
    workflow_nodes.execute_route_score(ctx, RouteScoreConfig())

    assert captured["cost_bias"] == 0.7


def _join_ctx(branch_ports: list[str]) -> WorkflowContext:
    ctx = WorkflowContext(session=None, job=None, prompt="", params={})  # type: ignore[arg-type]
    ctx.state["_branch_results"] = [NodeResult(port=p) for p in branch_ports]
    return ctx


def test_join_barrier_mode_requires_every_branch_to_land_on_a_success_port() -> None:
    config = JoinConfig(mode="barrier", success_ports=["ok"])
    assert execute_join(_join_ctx(["ok", "ok"]), config).port == "ok"
    assert execute_join(_join_ctx(["ok", "no_candidate"]), config).port == "partial_failure"


def test_join_race_mode_only_needs_one_branch_to_land_on_a_success_port() -> None:
    config = JoinConfig(mode="race", success_ports=["ok"])
    assert execute_join(_join_ctx(["ok", "no_candidate"]), config).port == "ok"
    both_failed = execute_join(_join_ctx(["no_candidate", "no_candidate"]), config)
    assert both_failed.port == "partial_failure"


def test_join_with_no_collected_branch_results_defaults_to_ok() -> None:
    """Defensive default for a `join` node reached outside a fan-out (e.g. a
    custom graph wiring it in directly) — should not crash the run."""
    ctx = WorkflowContext(session=None, job=None, prompt="", params={})  # type: ignore[arg-type]
    assert execute_join(ctx, JoinConfig()).port == "ok"


def _two_custom_agent_graph() -> WorkflowGraph:
    """Two `custom_agent` nodes in a row, both emitting `JobEventType.PROGRESS`.

    The scenario `WorkflowSteps.tsx` used to get wrong: without `node_id`,
    reverse-mapping by `event_type` alone cannot tell these two nodes' events
    (or their `AgentRun`s) apart.
    """
    nodes = [
        {
            "id": "judge_one",
            "type": "custom_agent",
            "config": {"agent_role": "judge_one_role", "output_key": "judge_one"},
        },
        {
            "id": "judge_two",
            "type": "custom_agent",
            "config": {"agent_role": "judge_two_role", "output_key": "judge_two"},
        },
        {"id": "fail", "type": "fail", "config": {}},
    ]
    edges = [
        {"id": "e1", "from": "judge_one", "from_port": "ok", "to": "judge_two"},
        {"id": "e2", "from": "judge_two", "from_port": "ok", "to": "fail"},
    ]
    return WorkflowGraph.from_dict({"nodes": nodes, "edges": edges})


def test_two_custom_agent_nodes_each_get_their_own_events_and_agent_runs_tagged(
    db: Session, author: User
) -> None:
    """Regression test for the `event_type` collision this feature fixes.

    Real (non-dry-run) walk through a graph with two `custom_agent` nodes:
    each node's `JobEvent`/`AgentRun` must carry that node's own id, not the
    other one's or none at all.
    """
    credits_service.grant(db, author.id, 5_000, idempotency_key=new_id("grant"))
    job = jobs_service.submit(
        db,
        user_id=author.id,
        operation=Operation.TEXT_TO_IMAGE,
        quality_tier=QualityTier.STANDARD,
        params={"prompt": "两个自定义判断节点", "aspect_ratio": "16:9"},
        idempotency_key=new_id("idk"),
    ).job

    params = dict(job.request_json)
    ctx = WorkflowContext(session=db, job=job, prompt=str(params.get("prompt", "")), params=params)
    WorkflowRunner(_two_custom_agent_graph()).run(ctx)

    progress_events = list(
        db.scalars(
            select(JobEvent)
            .where(JobEvent.job_id == job.id, JobEvent.event_type == JobEventType.PROGRESS)
            .order_by(JobEvent.sequence)
        )
    )
    assert [e.node_id for e in progress_events] == ["judge_one", "judge_two"]

    agent_runs = list(
        db.scalars(
            select(AgentRun)
            .where(AgentRun.job_id == job.id)
            .order_by(AgentRun.created_at, AgentRun.id)
        )
    )
    assert [r.agent_name for r in agent_runs] == ["judge_one_role", "judge_two_role"]
    assert [r.node_id for r in agent_runs] == ["judge_one", "judge_two"]


def _copy_generate_graph() -> WorkflowGraph:
    """`copy_generate` (with follow-up questions on) straight into `fail`.

    `fail` rather than `settle_success` on purpose: the point of this graph
    is only to observe the suspend/resume handoff, and `fail` needs no
    generated asset to reach its terminal state.
    """
    nodes = [
        {
            "id": "copy",
            "type": "copy_generate",
            "config": {"output_key": "copy_suggestion", "allow_followup_question": True},
        },
        {"id": "fail", "type": "fail", "config": {}},
    ]
    edges = [{"id": "e1", "from": "copy", "from_port": "ok", "to": "fail"}]
    return WorkflowGraph.from_dict({"nodes": nodes, "edges": edges})


def test_copy_generate_with_a_sparse_prompt_suspends_the_job_awaiting_input(
    db: Session, author: User
) -> None:
    """The fake gateway's copy agent `clarify` slot asks for a scene when the
    prompt is under 20 characters (`tests.fake_llm_gateway._copy_clarify`) —
    short enough to drive this deterministically without a real model."""
    credits_service.grant(db, author.id, 5_000, idempotency_key=new_id("grant"))
    job = jobs_service.submit(
        db,
        user_id=author.id,
        operation=Operation.TEXT_TO_IMAGE,
        quality_tier=QualityTier.STANDARD,
        params={"prompt": "一只猫", "aspect_ratio": "16:9"},
        idempotency_key=new_id("idk"),
    ).job
    sm.transition(db, job.id, JobStatus.QUEUED)
    job = sm.transition(db, job.id, JobStatus.RUNNING)

    params = dict(job.request_json)
    ctx = WorkflowContext(session=db, job=job, prompt=str(params.get("prompt", "")), params=params)
    outcome = WorkflowRunner(_copy_generate_graph()).run(ctx)

    assert outcome.status == JobStatus.AWAITING_INPUT
    db.refresh(job)
    assert job.status == JobStatus.AWAITING_INPUT

    request = input_requests.find_for_job(db, job.id)
    assert request is not None
    assert request.node_id == "copy"
    assert request.output_key == "copy_suggestion"
    question_ids = [q["id"] for q in request.questions_json]
    assert question_ids == ["scene", "action"]

    awaiting_events = list(
        db.scalars(
            select(JobEvent).where(
                JobEvent.job_id == job.id, JobEvent.event_type == JobEventType.AWAITING_INPUT
            )
        )
    )
    assert len(awaiting_events) == 1


def test_validate_answers_rejects_a_missing_required_question() -> None:
    questions = [
        {
            "id": "scene",
            "kind": "single_choice",
            "prompt": "画面发生在什么场景？",
            "options": [{"value": "indoor", "label": "室内"}],
            "required": True,
        }
    ]
    with pytest.raises(Exception, match="必须回答"):
        input_requests.validate_answers(questions, {})


def test_validate_answers_rejects_an_option_outside_the_question() -> None:
    questions = [
        {
            "id": "scene",
            "kind": "single_choice",
            "prompt": "画面发生在什么场景？",
            "options": [{"value": "indoor", "label": "室内"}],
            "required": True,
        }
    ]
    with pytest.raises(Exception, match="选项不合法"):
        input_requests.validate_answers(questions, {"scene": "not_an_option"})


def test_answering_an_input_request_resumes_the_graph_to_its_next_node(
    db: Session, author: User
) -> None:
    """End-to-end: suspend, validate + merge the answer, resume — mirrors
    what `POST /v1/generation-jobs/{id}/answer` does, minus the HTTP layer."""
    credits_service.grant(db, author.id, 5_000, idempotency_key=new_id("grant"))
    job = jobs_service.submit(
        db,
        user_id=author.id,
        operation=Operation.TEXT_TO_IMAGE,
        quality_tier=QualityTier.STANDARD,
        params={"prompt": "一只猫", "aspect_ratio": "16:9"},
        idempotency_key=new_id("idk"),
    ).job
    sm.transition(db, job.id, JobStatus.QUEUED)
    job = sm.transition(db, job.id, JobStatus.RUNNING)

    graph = _copy_generate_graph()
    params = dict(job.request_json)
    ctx = WorkflowContext(session=db, job=job, prompt=str(params.get("prompt", "")), params=params)
    WorkflowRunner(graph).run(ctx)

    request = input_requests.find_for_job(db, job.id)
    assert request is not None
    answers = input_requests.validate_answers(request.questions_json, {"scene": "indoor"})
    assert answers == {"scene": "indoor"}

    resume_ctx = WorkflowContext(
        session=db, job=job, prompt=str(params.get("prompt", "")), params=params
    )
    checkpoint_state = dict(request.state_checkpoint_json or {})
    output = dict(checkpoint_state.get("output_value") or {})
    output["clarify_answers"] = answers
    resume_ctx.state[request.output_key] = output
    node_id = request.node_id

    input_requests.settle(db, request)
    job = sm.transition(db, job.id, JobStatus.RUNNING)
    resume_ctx.job = job

    outcome = WorkflowRunner(graph).resume(resume_ctx, node_id=node_id, port="ok")

    assert outcome.status == JobStatus.FAILED
    db.refresh(job)
    assert job.status == JobStatus.FAILED
    assert input_requests.find_for_job(db, job.id) is None


def _planning_graph(*, allow_followup_question: bool = True) -> WorkflowGraph:
    """`planning` (reverse-questioning on) straight into `fail`.

    Same shape and reasoning as `_copy_generate_graph`: only the suspend/
    resume handoff matters here, so `fail` is close enough to a terminal
    state without needing a generated asset.
    """
    nodes = [
        {
            "id": "planning",
            "type": "planning",
            "config": {"output_key": "plan", "allow_followup_question": allow_followup_question},
        },
        {"id": "fail", "type": "fail", "config": {}},
    ]
    edges = [{"id": "e1", "from": "planning", "from_port": "ok", "to": "fail"}]
    return WorkflowGraph.from_dict({"nodes": nodes, "edges": edges})


def _running_job(
    db: Session, author: User, *, prompt: str, origin: str = JobOrigin.USER
) -> WorkflowContext:
    credits_service.grant(db, author.id, 5_000, idempotency_key=new_id("grant"))
    job = jobs_service.submit(
        db,
        user_id=author.id,
        operation=Operation.TEXT_TO_IMAGE,
        quality_tier=QualityTier.STANDARD,
        params={"prompt": prompt, "aspect_ratio": "16:9"},
        idempotency_key=new_id("idk"),
        origin=origin,
    ).job
    sm.transition(db, job.id, JobStatus.QUEUED)
    job = sm.transition(db, job.id, JobStatus.RUNNING)
    params = dict(job.request_json)
    return WorkflowContext(session=db, job=job, prompt=str(params.get("prompt", "")), params=params)


def test_planning_with_the_clarify_marker_suspends_the_job_awaiting_input(
    db: Session, author: User
) -> None:
    """The fake gateway's planner `clarify` slot only asks when the intent
    contains `PLANNER_CLARIFY_MARKER` (`tests.fake_llm_gateway._planner_clarify`)
    — short enough to drive this deterministically without a real model, and
    explicit enough that no unrelated test's placeholder prompt accidentally
    triggers it."""
    ctx = _running_job(db, author, prompt=f"{PLANNER_CLARIFY_MARKER}：香港街头斗殴")
    outcome = WorkflowRunner(_planning_graph()).run(ctx)

    assert outcome.status == JobStatus.AWAITING_INPUT
    db.refresh(ctx.job)
    assert ctx.job.status == JobStatus.AWAITING_INPUT

    request = input_requests.find_for_job(db, ctx.job.id)
    assert request is not None
    assert request.node_id == "planning"
    assert request.output_key == "plan"
    question_ids = [q["id"] for q in request.questions_json]
    assert question_ids == ["subject_count", "camera"]
    # Planning suspends before `route_score`; a default of 1 here used to
    # make the first real provider attempt land as attempt 2.
    assert request.state_checkpoint_json.get("route_attempts") == 0

    awaiting_events = list(
        db.scalars(
            select(JobEvent).where(
                JobEvent.job_id == ctx.job.id, JobEvent.event_type == JobEventType.AWAITING_INPUT
            )
        )
    )
    assert len(awaiting_events) == 1


def test_awaiting_input_is_published_only_after_the_input_request_row_exists(
    db: Session, author: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The C-end mounts AwaitingInputPanel on the SSE frame, then GETs
    `/input-request`. Publishing that frame before `suspend` + `transition`
    made the GET 404 and the panel never retried.

    Both `nodes` and `runner` look up `publisher.publish_job_event` on the
    module at call time, so patching here captures the live Redis publish.
    """
    snapshots: list[tuple[bool, JobStatus | None]] = []

    def capture(job_id: str, payload: dict[str, object]) -> None:
        if payload.get("event_type") != JobEventType.AWAITING_INPUT.value:
            return
        request = input_requests.find_for_job(db, job_id)
        job = db.get(GenerationJob, job_id)
        snapshots.append((request is not None, JobStatus(job.status) if job else None))

    monkeypatch.setattr(publisher, "publish_job_event", capture)

    ctx = _running_job(db, author, prompt=f"{PLANNER_CLARIFY_MARKER}：香港街头斗殴")
    outcome = WorkflowRunner(_planning_graph()).run(ctx)

    assert outcome.status == JobStatus.AWAITING_INPUT
    assert snapshots == [(True, JobStatus.AWAITING_INPUT)]
    awaiting_events = list(
        db.scalars(
            select(JobEvent).where(
                JobEvent.job_id == ctx.job.id, JobEvent.event_type == JobEventType.AWAITING_INPUT
            )
        )
    )
    assert len(awaiting_events) == 1


def test_sandbox_planning_clarify_still_suspends_awaiting_input(db: Session, author: User) -> None:
    """Product sandbox is a real job: the planner's follow-up must park it
    the same way a C-end request does, so the editor can render the questions.
    `WorkflowContext.dry_run` is the only path that skips clarify."""
    ctx = _running_job(
        db,
        author,
        prompt=f"{PLANNER_CLARIFY_MARKER}：雨后的东京街头",
        origin=JobOrigin.SANDBOX,
    )
    assert ctx.is_sandbox
    outcome = WorkflowRunner(_planning_graph()).run(ctx)

    assert outcome.status == JobStatus.AWAITING_INPUT
    db.refresh(ctx.job)
    assert ctx.job.status == JobStatus.AWAITING_INPUT
    request = input_requests.find_for_job(db, ctx.job.id)
    assert request is not None
    assert [q["id"] for q in request.questions_json] == ["subject_count", "camera"]


def test_planning_clarify_skips_subject_when_reference_material_is_present(
    db: Session, author: User
) -> None:
    """A remix / video-to-video job already carries the source clip on
    `reference_asset_ids`. The clarify slot must not then ask who/what the
    subject is — only questions the reference cannot answer (camera here).
    The no-reference control is `test_sandbox_planning_clarify_still_
    suspends_awaiting_input` (`["subject_count", "camera"]`).
    """
    ctx = _running_job(db, author, prompt=f"{PLANNER_CLARIFY_MARKER}：把这段改成夜戏")
    ctx.params["reference_asset_ids"] = ["ast_test"]
    outcome = WorkflowRunner(_planning_graph()).run(ctx)

    assert outcome.status == JobStatus.AWAITING_INPUT
    request = input_requests.find_for_job(db, ctx.job.id)
    assert request is not None
    assert [q["id"] for q in request.questions_json] == ["camera"]


def test_planning_clarify_from_created_reaches_awaiting_input(db: Session, author: User) -> None:
    """The default graph's planner sits before `provider_generate`.

    A live clarify therefore fires while the job is still `queued` (the
    worker has only taken CREATED → QUEUED). `AWAITING_INPUT` is only a
    legal successor of `RUNNING`, so the engine must promote first.
    """
    credits_service.grant(db, author.id, 5_000, idempotency_key=new_id("grant"))
    job = jobs_service.submit(
        db,
        user_id=author.id,
        operation=Operation.TEXT_TO_IMAGE,
        quality_tier=QualityTier.STANDARD,
        params={"prompt": f"{PLANNER_CLARIFY_MARKER}：香港街头斗殴", "aspect_ratio": "16:9"},
        idempotency_key=new_id("idk"),
    ).job
    params = dict(job.request_json)
    ctx = WorkflowContext(session=db, job=job, prompt=str(params.get("prompt", "")), params=params)
    outcome = WorkflowRunner(_planning_graph()).run(ctx)

    assert outcome.status == JobStatus.AWAITING_INPUT
    db.refresh(job)
    assert job.status == JobStatus.AWAITING_INPUT
    assert input_requests.find_for_job(db, job.id) is not None


def test_cancel_during_planning_does_not_park_awaiting_input(
    db: Session, author: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reported bug: cancel arrives while the planner is still thinking,
    then the node tries to suspend. The runner must honour the flag after the
    node returns and never write a `WorkflowInputRequest`."""
    from app.agents import planner as planner_agent

    ctx = _running_job(db, author, prompt=f"{PLANNER_CLARIFY_MARKER}：香港街头斗殴")
    original = planner_agent.clarify

    def _clarify_then_cancel(*args: object, **kwargs: object):
        outcome = original(*args, **kwargs)
        sm.request_cancel(db, ctx.job.id)
        return outcome

    monkeypatch.setattr("app.workflows.nodes.planner.clarify", _clarify_then_cancel)
    outcome = WorkflowRunner(_planning_graph()).run(ctx)

    assert outcome.status == JobStatus.CANCELLED
    db.refresh(ctx.job)
    assert ctx.job.status == JobStatus.CANCELLED
    assert input_requests.find_for_job(db, ctx.job.id) is None


def test_planning_without_the_clarify_marker_does_not_suspend_by_default(
    db: Session, author: User
) -> None:
    """`allow_followup_question` defaults to `True`, but a plan the stub judges
    sufficient must still fall straight through — the default must not turn
    every job into a follow-up prompt."""
    ctx = _running_job(db, author, prompt="海边的黄昏，长镜头")
    outcome = WorkflowRunner(_planning_graph()).run(ctx)

    assert outcome.status == JobStatus.FAILED
    assert input_requests.find_for_job(db, ctx.job.id) is None


def test_planning_with_followup_disabled_never_suspends_even_with_the_marker(
    db: Session, author: User
) -> None:
    """The opt-out path: a graph that explicitly sets `allow_followup_question
    = False` must behave exactly like before this feature, regardless of what
    the clarify slot would have said."""
    ctx = _running_job(db, author, prompt=f"{PLANNER_CLARIFY_MARKER}：香港街头斗殴")
    outcome = WorkflowRunner(_planning_graph(allow_followup_question=False)).run(ctx)

    assert outcome.status == JobStatus.FAILED
    assert input_requests.find_for_job(db, ctx.job.id) is None


def test_asset_kind_graphs_seed_the_planning_node_with_followup_disabled(
    db: Session, author: User
) -> None:
    """Regression: a character/scene/cover job's `planning` node used to be
    seeded with `config: {}` (`allow_followup_question` defaulting `True`),
    so a "补全侧面/背面" completion job — whose prompt is often just the
    character's bare name (see `character-library.tsx`'s `completeViews`) —
    got misread by the generic clarify slot as missing scene/action/shot
    info and suspended at `AWAITING_INPUT` asking for exactly what a
    character asset must NOT have (see `app.agents.planner
    ._ASSET_KIND_BRIEF`). The image studio never renders `AwaitingInputPanel`
    for that, so the job hung forever. `asset_graph` must keep opting the
    `planning` node out, regardless of what the clarify slot would say.
    """
    graph = asset_graph(db, ImageAssetKind.CHARACTER.value)
    planning_config = next(node for node in graph["nodes"] if node["id"] == "planning")["config"]

    # A bare character name, same shape `completeViews` actually submits —
    # short enough that the real clarify agent (not just the fake gateway's
    # marker) would very plausibly ask for a scene/action/shot too.
    ctx = _running_job(db, author, prompt=f"{PLANNER_CLARIFY_MARKER}：叶文洁")
    outcome = execute_planning(ctx, PlanningConfig(**planning_config))

    assert outcome.suspend is False
    assert input_requests.find_for_job(db, ctx.job.id) is None


def test_provider_generate_folds_the_plan_into_the_effective_prompt(
    db: Session, author: User, monkeypatch: pytest.MonkeyPatch, fake_media_catalog: None
) -> None:
    """`prompt_enhancements`/`negative_prompt_suggestions` must actually reach
    the provider, not just sit in an `AgentRun` log
    (`app.workflows.nodes._plan_enhancements`)."""
    ctx = _running_job(db, author, prompt="海边的黄昏，长镜头")
    execute_planning(ctx, PlanningConfig(allow_followup_question=False))
    execute_route_score(ctx, RouteScoreConfig())
    decision = ctx.state["decision"]
    assert decision.provider is not None

    captured: dict[str, object] = {}
    real_submit = decision.provider.submit

    def capture_submit(request):  # type: ignore[no-untyped-def]
        captured["request"] = request
        return real_submit(request)

    monkeypatch.setattr(decision.provider, "submit", capture_submit)

    execute_provider_generate(ctx, ProviderGenerateConfig())

    request = captured["request"]
    assert request.prompt.startswith("海边的黄昏，长镜头")
    assert "电影感布光" in request.prompt
    assert "浅景深" in request.prompt
    assert request.negative_prompt is not None
    assert "肢体畸变" in request.negative_prompt


@pytest.mark.parametrize(
    "asset_params",
    [
        {"asset_kind": ImageAssetKind.CHARACTER.value, "character_view": CharacterViewAngle.SIDE.value},
        {"video_asset_kind": VideoAssetKind.CHARACTER_ACTION.value},
    ],
    ids=["image_asset_kind", "video_asset_kind"],
)
def test_provider_generate_ignores_the_generic_plan_for_an_asset_kind_job(
    db: Session,
    author: User,
    monkeypatch: pytest.MonkeyPatch,
    fake_media_catalog: None,
    asset_params: dict[str, str],
) -> None:
    """The bug: a multi-view `CHARACTER` completion job's generic `planning`
    node runs once, before the per-view loop starts, already describing
    every remaining view at once (real dev-DB `agent_runs` row: a "side"/
    "back" job's generic plan enhancement literally read "侧面图展示...
    背面图展示..."). Re-folding that same cached plan into *every* loop
    pass leaked the other view's description into this pass's prompt, and
    could also override the real reference photo with a physical
    description the context-blind planner invented from text alone.
    `_plan_enhancements` must ignore the generic plan for any asset-kind job
    (image or video), regardless of what the fake gateway's planner stub
    says — `execute_asset_planning` owns prompt guidance for these kinds.
    """
    ctx = _running_job(db, author, prompt="海边的黄昏，长镜头")
    ctx.params.update(asset_params)
    execute_planning(ctx, PlanningConfig(allow_followup_question=False))
    execute_route_score(ctx, RouteScoreConfig())
    decision = ctx.state["decision"]
    assert decision.provider is not None

    captured: dict[str, object] = {}
    real_submit = decision.provider.submit

    def capture_submit(request):  # type: ignore[no-untyped-def]
        captured["request"] = request
        return real_submit(request)

    monkeypatch.setattr(decision.provider, "submit", capture_submit)

    execute_provider_generate(ctx, ProviderGenerateConfig())

    request = captured["request"]
    assert request.prompt == "海边的黄昏，长镜头"
    assert "电影感布光" not in request.prompt
    assert "浅景深" not in request.prompt
    assert request.negative_prompt is None
