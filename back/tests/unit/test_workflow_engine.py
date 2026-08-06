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

from app.workflows import registry
from app.workflows.configs import JoinConfig, RouteScoreConfig
from app.workflows.defaults import default_graph
from app.workflows.graph import WorkflowGraph
from app.workflows.graph import validate as validate_graph
from app.workflows.nodes import execute_join
from app.workflows.types import NodeResult, WorkflowContext

_REGISTRY_TYPES = set(registry.NODE_TYPES.keys())


def _validate(graph_dict: dict) -> list[str]:
    return validate_graph(WorkflowGraph.from_dict(graph_dict), registry_types=_REGISTRY_TYPES)


def test_the_seeded_default_graph_is_valid_for_every_registered_node_type() -> None:
    """The one graph every `Operation` actually ships with must always pass
    its own validator — a regression here would brick every new job."""
    errors = _validate(default_graph())
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
