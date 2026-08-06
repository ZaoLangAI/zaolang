"""The declared shape of one operation's generation workflow.

Used by the ops console to render a timeline even for a job that failed
before emitting its later steps (`WorkflowSteps` on the frontend overlays
real `JobEvent`s onto this declared list). Unlike the old hardcoded
`GENERATION_STEPS`, this is derived live from the operation's active
`GenerationWorkflowTemplate` graph — a step an admin adds or removes shows up
here on the next request, no deploy required.
"""

from __future__ import annotations

from functools import partial
from typing import Any

from sqlalchemy.orm import Session

from app.domain.workflow_templates import service as workflow_templates_service
from app.workflows import registry
from app.workflows.defaults import default_graph
from app.workflows.graph import TERMINAL_NODE_TYPES, WorkflowEdge, WorkflowGraph, WorkflowNode


def describe_workflow(session: Session, operation: str) -> dict[str, Any]:
    template = workflow_templates_service.get_active(session, operation)
    graph = WorkflowGraph.from_dict(template.graph_json if template else default_graph())

    return {
        "operation": operation,
        "name": template.name if template else "默认生成流程",
        "version": template.version if template else None,
        "description": (
            "按已发布的节点图执行；终态节点保证一次预扣积分最终恰好一次 capture 或 release。"
        ),
        "steps": [_step(node) for node in _happy_path(graph) if _step(node) is not None],
    }


def _step(node: WorkflowNode) -> dict[str, Any] | None:
    spec = registry.NODE_TYPES.get(node.type)
    if spec is None or spec.event_type is None:
        # Internal/context-only steps (e.g. `skill_context`) and the failure
        # terminal (`fail`, never reached by the happy-path walk below) do
        # not correspond to one public `JobEvent` a timeline row can light up
        # on, so they are left out of the declared shape entirely.
        return None
    return {
        "key": node.id,
        "label": spec.label,
        "node_type": node.type,
        "event_type": spec.event_type.value,
        "is_agent": spec.is_agent,
        "agent_role": spec.agent_role,
    }


def _port_rank(edge: WorkflowEdge, ports: tuple[str, ...]) -> int:
    return ports.index(edge.from_port) if edge.from_port in ports else len(ports)


def _happy_path(graph: WorkflowGraph) -> list[WorkflowNode]:
    """Walks the graph's successful route from entry to a terminal node.

    At each node, follows whichever `sequential` edge leaves from the port
    that appears first in that node type's `output_ports` — by convention the
    "everything is fine" port (`registry.py` always lists it first). Retry
    edges loop backwards and parallel edges have no single "next" node to
    show on a linear timeline, so only `sequential` edges are ever chosen;
    this is a display aid, not a re-implementation of the runner.
    """
    node_map = graph.node_map
    incoming = {e.to_node for e in graph.edges}
    entries = [n.id for n in graph.nodes if n.id not in incoming]
    if not entries:
        return []

    order: list[WorkflowNode] = []
    visited: set[str] = set()
    current = entries[0]
    while current not in visited:
        visited.add(current)
        node = node_map[current]
        order.append(node)
        if node.type in TERMINAL_NODE_TYPES:
            break

        candidates = [e for e in graph.edges_from(current) if e.kind == "sequential"]
        if not candidates:
            break
        spec = registry.NODE_TYPES.get(node.type)
        ports = spec.output_ports if spec else ()
        candidates.sort(key=partial(_port_rank, ports=ports))
        current = candidates[0].to_node
    return order
