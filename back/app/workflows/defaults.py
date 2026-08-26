"""The seed graphs every `Operation`/asset-kind combination starts with.

`default_graph` is a 1:1 reproduction of the pre-engine hardcoded pipeline
(`app.workers.pipeline`, now retired) plus the `intent_router` step. Every
`Operation` gets this exact same shape at seed time — whether a given
operation currently has any eligible provider is a runtime routing outcome
(`route_score` -> `no_candidate`), not a structural difference worth encoding
per operation.

`asset_graph` is the same shape with three extra nodes spliced in for a
non-`GENERAL` `ImageAssetKind`/`VideoAssetKind` job (image: character /
scene / cover; video: character_action / transition_video /
cover_video): `asset_planning` right before routing, so the planner's
guidance can steer the actual generation; `asset_output_advance` right after
quality passes, which loops back to `asset_planning` once per remaining
`GenerationParams.character_views` entry for a multi-view image `CHARACTER`
job (a no-op single pass for everything else, including every video kind —
no video kind ever loops); and `asset_output_link`, once every view is
done, so the successful output(s) auto-attach to their target character/
scene skill (an image reference, or a video `action_clips` entry).
See `app.domain.workflow_templates.service.ensure_default_templates`,
the only place all three are seeded. The graph shape itself is identical for
both media types — only the node executors (`app.workflows.nodes`) branch
on which asset-kind axis is active.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.domain.agent_skills import service as agent_skills_service

# The static `AgentBinding`s (`registry.NODE_TYPES`) every seed graph wires
# up: (node id, config field, role). `asset_planning` reuses the `planner`
# role's default profile too — same convention as `intent_router` appearing
# twice under different slots.
_STATIC_BINDINGS: tuple[tuple[str, str, str], ...] = (
    ("safety", "agent_id", "safety"),
    ("planning", "agent_id", "planner"),
    ("intent_router", "agent_id", "intent_router"),
    ("asset_planning", "agent_id", "planner"),
    ("quality_check", "agent_id", "quality"),
    ("route_score", "selector_agent_id", "intent_router"),
)


def default_graph(session: Session) -> dict[str, Any]:
    return _build_graph(session, with_asset_nodes=False)


def asset_graph(session: Session, asset_kind: str) -> dict[str, Any]:
    """The asset-kind variant of `default_graph`, shared by image and video.

    `asset_kind` is not baked into the graph itself — every non-`GENERAL`
    kind (image or video) shares this exact same shape, since the extra
    nodes read `ctx.params["asset_kind"]`/`ctx.params["video_asset_kind"]`
    at run time rather than the operator having to author one graph per
    kind. The parameter exists so a future kind that genuinely needs a
    different shape can special-case it here without changing
    `ensure_default_templates`'s call site.
    """
    return _build_graph(session, with_asset_nodes=True)


def _build_graph(session: Session, *, with_asset_nodes: bool) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = [
        {"id": "safety", "type": "safety_check", "config": {}, "position": {"x": 0, "y": 0}},
        {
            "id": "skill_context",
            "type": "skill_context",
            "config": {},
            "position": {"x": 220, "y": 0},
        },
        {
            "id": "planning",
            "type": "planning",
            # An asset-kind graph's own `asset_planning` node already runs a
            # dedicated, context-aware plan (`asset_kind`/`character_view`
            # aware) right after this — the generic `planning` node's clarify
            # slot has neither, so it judges a bare completion-job prompt
            # (e.g. just a character's name, see `character-library.tsx`'s
            # "补全侧面/背面") as missing scene/action/shot info and asks for
            # exactly the things a character/scene/cover asset must NOT have
            # (see `planner._ASSET_KIND_BRIEF`). Suspending here also can't be
            # recovered from in the image studio, which never renders
            # `AwaitingInputPanel` (see `zaolang-frontend-ui` invariant #18).
            # For the same "no context" reason, this node's own `plan()`
            # call still runs (unchanged cost/progress/checkpoint) but its
            # `prompt_enhancements`/`negative_prompt_suggestions` are never
            # folded into the actual generation request for these kinds —
            # see `app.workflows.nodes._plan_enhancements`.
            "config": {"allow_followup_question": False} if with_asset_nodes else {},
            "position": {"x": 440, "y": 0},
        },
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
    if with_asset_nodes:
        nodes.append(
            {
                "id": "asset_planning",
                "type": "asset_planning",
                "config": {},
                "position": {"x": 770, "y": -140},
            }
        )
        nodes.append(
            {
                "id": "asset_output_advance",
                "type": "asset_output_advance",
                "config": {},
                "position": {"x": 1430, "y": -140},
            }
        )
        nodes.append(
            {
                "id": "asset_output_link",
                "type": "asset_output_link",
                "config": {},
                "position": {"x": 1650, "y": -140},
            }
        )

    # Bind each judgment node to whatever agent is currently the role's
    # default, so a freshly seeded workflow is editable/visible in the
    # console from day one instead of showing an opaque "role default".
    # A role with no default agent yet (empty DB, `ensure_default_profiles`
    # not run) is left unset — the existing "empty = role default, resolved
    # at run time" fallback still applies, so seeding never fails on this.
    nodes_by_id = {node["id"]: node for node in nodes}
    for node_id, config_field, role in _STATIC_BINDINGS:
        if node_id not in nodes_by_id:
            continue
        profile = agent_skills_service.default_profile(session, role)
        if profile is not None:
            nodes_by_id[node_id]["config"][config_field] = profile.id

    edges = [
        _edge("safety", "pass", "skill_context"),
        _edge("safety", "reject", "fail"),
        _edge("skill_context", "ok", "planning"),
        _edge("planning", "ok", "intent_router"),
        _edge("intent_router", "ok", "asset_planning" if with_asset_nodes else "route_score"),
        _edge("route_score", "ok", "provider_generate"),
        _edge("route_score", "no_candidate", "fail"),
        _edge("route_score", "retries_exhausted", "fail"),
        _edge("provider_generate", "succeeded", "quality_check"),
        _edge("provider_generate", "retry", "route_score", kind="retry"),
        _edge("provider_generate", "failed", "fail"),
        _edge(
            "quality_check",
            "pass",
            "asset_output_advance" if with_asset_nodes else "settle_success",
        ),
        _edge("quality_check", "retry", "route_score", kind="retry"),
        _edge("quality_check", "fail", "fail"),
    ]
    if with_asset_nodes:
        edges.append(_edge("asset_planning", "ok", "route_score"))
        # A multi-view `CHARACTER` job's remaining views loop back here
        # rather than falling through to `asset_output_link` — see
        # `execute_asset_output_advance`. Marked `retry` kind (not
        # structurally different from `sequential` to the runner, just the
        # same "controlled cycle" label `quality_check:retry` uses above).
        edges.append(_edge("asset_output_advance", "next", "asset_planning", kind="retry"))
        edges.append(_edge("asset_output_advance", "done", "asset_output_link"))
        edges.append(_edge("asset_output_link", "ok", "settle_success"))
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
