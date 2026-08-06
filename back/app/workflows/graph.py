"""Workflow graph model and structural validation.

A `WorkflowGraph` is the admin-configurable shape of one operation's
generation pipeline: nodes are instances of a code-reviewed node type (see
`registry.py`); edges say which node's output port feeds which node next.
`validate()` is the safety net that keeps an operator from publishing a graph
that could strand a job without a terminal state or loop forever — the same
role `platform_config.service.validate` plays for plain config values.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Literal

EdgeKind = Literal["sequential", "parallel", "retry"]

# The two node types allowed to call `jobs_service.settle_*` /
# `state_machine.transition(..., terminal)`. Every path through a published
# graph must end in one of these.
TERMINAL_NODE_TYPES = frozenset({"settle_success", "fail"})

# Absolute ceiling on how many times the runner will execute any single node
# for one job, regardless of what a node's own loop-budget config says. The
# last line of defence against a graph that validation somehow let through.
HARD_MAX_NODE_VISITS = 20


@dataclass(slots=True)
class WorkflowNode:
    id: str
    type: str
    config: dict[str, Any] = field(default_factory=dict)
    position: dict[str, float] = field(default_factory=dict)


@dataclass(slots=True)
class WorkflowEdge:
    id: str
    from_node: str
    from_port: str
    to_node: str
    kind: EdgeKind = "sequential"


@dataclass(slots=True)
class WorkflowGraph:
    nodes: list[WorkflowNode]
    edges: list[WorkflowEdge]

    @property
    def node_map(self) -> dict[str, WorkflowNode]:
        return {n.id: n for n in self.nodes}

    def edges_from(self, node_id: str, port: str | None = None) -> list[WorkflowEdge]:
        return [
            e
            for e in self.edges
            if e.from_node == node_id and (port is None or e.from_port == port)
        ]

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> WorkflowGraph:
        nodes = [
            WorkflowNode(
                id=str(n["id"]),
                type=str(n["type"]),
                config=dict(n.get("config") or {}),
                position=dict(n.get("position") or {}),
            )
            for n in payload.get("nodes", [])
        ]
        edges = [
            WorkflowEdge(
                id=str(e.get("id") or f"{e['from']}:{e.get('from_port', 'ok')}->{e['to']}"),
                from_node=str(e["from"]),
                from_port=str(e.get("from_port", "ok")),
                to_node=str(e["to"]),
                kind=e.get("kind", "sequential"),
            )
            for e in payload.get("edges", [])
        ]
        return cls(nodes=nodes, edges=edges)

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": [
                {"id": n.id, "type": n.type, "config": n.config, "position": n.position}
                for n in self.nodes
            ],
            "edges": [
                {
                    "id": e.id,
                    "from": e.from_node,
                    "from_port": e.from_port,
                    "to": e.to_node,
                    "kind": e.kind,
                }
                for e in self.edges
            ],
        }


def validate(graph: WorkflowGraph, *, registry_types: set[str]) -> list[str]:
    """Structural checks a graph must pass before it can be published.

    Returns human-readable problems; an empty list means the graph is safe to
    run. Never raises — the caller (the admin API) decides what a non-empty
    list means for the request.
    """
    errors: list[str] = []

    if not graph.nodes:
        return ["图不能为空。"]

    seen_ids: set[str] = set()
    for node in graph.nodes:
        if node.id in seen_ids:
            errors.append(f"节点 id 重复: {node.id}")
        seen_ids.add(node.id)
        if node.type not in registry_types:
            errors.append(f"未知节点类型: {node.type} ({node.id})")

    node_map = graph.node_map
    for edge in graph.edges:
        if edge.from_node not in node_map:
            errors.append(f"连线引用了不存在的起点节点: {edge.from_node}")
        if edge.to_node not in node_map:
            errors.append(f"连线引用了不存在的终点节点: {edge.to_node}")
    if errors:
        # The shape checks below all assume every id resolves.
        return errors

    incoming: dict[str, int] = defaultdict(int)
    outgoing: dict[str, list[WorkflowEdge]] = defaultdict(list)
    for edge in graph.edges:
        incoming[edge.to_node] += 1
        outgoing[edge.from_node].append(edge)

    entries = [n.id for n in graph.nodes if incoming.get(n.id, 0) == 0]
    if len(entries) != 1:
        errors.append(f"必须有且只有一个入口节点（无入边），当前有 {len(entries)} 个: {entries}")

    reachable: set[str] = set()
    if entries:
        queue = deque([entries[0]])
        reachable.add(entries[0])
        while queue:
            current = queue.popleft()
            for edge in outgoing.get(current, []):
                if edge.to_node not in reachable:
                    reachable.add(edge.to_node)
                    queue.append(edge.to_node)
    orphans = [n.id for n in graph.nodes if n.id not in reachable]
    if orphans:
        errors.append(f"存在无法从入口到达的孤立节点: {orphans}")

    reverse: dict[str, list[str]] = defaultdict(list)
    for edge in graph.edges:
        reverse[edge.to_node].append(edge.from_node)
    can_reach_terminal: set[str] = {
        n.id for n in graph.nodes if node_map[n.id].type in TERMINAL_NODE_TYPES
    }
    queue = deque(can_reach_terminal)
    while queue:
        current = queue.popleft()
        for pred in reverse.get(current, []):
            if pred not in can_reach_terminal:
                can_reach_terminal.add(pred)
                queue.append(pred)
    dead_ends = [
        n.id
        for n in graph.nodes
        if n.type not in TERMINAL_NODE_TYPES and n.id not in can_reach_terminal
    ]
    if dead_ends:
        errors.append(f"以下节点没有任何路径可以到达终态节点(settle_success/fail): {dead_ends}")

    # Fan-out/join: every group of >=2 parallel edges sharing one
    # (from_node, from_port) must converge on exactly one common join node.
    parallel_groups: dict[tuple[str, str], list[str]] = defaultdict(list)
    for edge in graph.edges:
        if edge.kind == "parallel":
            parallel_groups[(edge.from_node, edge.from_port)].append(edge.to_node)
    for (from_node, from_port), targets in parallel_groups.items():
        if len(targets) < 2:
            errors.append(f"{from_node}:{from_port} 只有一条并行分支，至少需要两条才需要 join。")
            continue
        joins = [_first_reachable_join(target, outgoing, node_map) for target in targets]
        if any(j is None for j in joins):
            errors.append(f"{from_node}:{from_port} 的并行分支中有一条无法到达 join 节点。")
        elif len(set(joins)) != 1:
            errors.append(f"{from_node}:{from_port} 的并行分支必须汇合到同一个 join 节点。")

    return errors


def _first_reachable_join(
    start: str, outgoing: dict[str, list[WorkflowEdge]], node_map: dict[str, WorkflowNode]
) -> str | None:
    visited: set[str] = set()
    queue = deque([start])
    while queue:
        current = queue.popleft()
        if current in visited:
            continue
        visited.add(current)
        if node_map[current].type == "join":
            return current
        for edge in outgoing.get(current, []):
            queue.append(edge.to_node)
    return None
