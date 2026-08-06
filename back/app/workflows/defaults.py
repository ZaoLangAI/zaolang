"""The seed graph every `Operation` starts with.

1:1 reproduction of the pre-engine hardcoded pipeline (`app.workers.pipeline`,
now retired) plus the new `intent_router` step. Every `Operation` gets this
exact same shape at seed time — whether a given operation currently has any
eligible provider is a runtime routing outcome (`route_score` ->
`no_candidate`), not a structural difference worth encoding per operation.
"""

from __future__ import annotations

from typing import Any


def default_graph() -> dict[str, Any]:
    nodes = [
        {"id": "safety", "type": "safety_check", "config": {}, "position": {"x": 0, "y": 0}},
        {
            "id": "skill_context",
            "type": "skill_context",
            "config": {},
            "position": {"x": 220, "y": 0},
        },
        {"id": "planning", "type": "planning", "config": {}, "position": {"x": 440, "y": 0}},
        {
            "id": "intent_router",
            "type": "intent_router",
            "config": {},
            "position": {"x": 660, "y": 0},
        },
        {
            "id": "route_score",
            "type": "route_score",
            "config": {"max_attempts": 2},
            "position": {"x": 880, "y": 0},
        },
        {
            "id": "provider_generate",
            "type": "provider_generate",
            "config": {"retry_on_failure": True},
            "position": {"x": 1100, "y": 0},
        },
        {
            "id": "quality_check",
            "type": "quality_check",
            "config": {},
            "position": {"x": 1320, "y": 0},
        },
        {
            "id": "settle_success",
            "type": "settle_success",
            "config": {},
            "position": {"x": 1540, "y": 0},
        },
        {"id": "fail", "type": "fail", "config": {}, "position": {"x": 760, "y": 260}},
    ]
    edges = [
        _edge("safety", "pass", "skill_context"),
        _edge("safety", "reject", "fail"),
        _edge("skill_context", "ok", "planning"),
        _edge("planning", "ok", "intent_router"),
        _edge("intent_router", "ok", "route_score"),
        _edge("route_score", "ok", "provider_generate"),
        _edge("route_score", "no_candidate", "fail"),
        _edge("route_score", "retries_exhausted", "fail"),
        _edge("provider_generate", "succeeded", "quality_check"),
        _edge("provider_generate", "retry", "route_score", kind="retry"),
        _edge("provider_generate", "failed", "fail"),
        _edge("quality_check", "pass", "settle_success"),
        _edge("quality_check", "retry", "route_score", kind="retry"),
        _edge("quality_check", "fail", "fail"),
    ]
    return {"nodes": nodes, "edges": edges}


def _edge(
    from_node: str, from_port: str, to_node: str, *, kind: str = "sequential"
) -> dict[str, Any]:
    return {
        "id": f"{from_node}:{from_port}->{to_node}",
        "from": from_node,
        "from_port": from_port,
        "to": to_node,
        "kind": kind,
    }
