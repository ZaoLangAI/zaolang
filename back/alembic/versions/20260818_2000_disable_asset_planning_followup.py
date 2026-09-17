"""disable the generic planning node's follow-up question on asset-kind templates

Revision ID: a9d4c7e2f8b1
Revises: f2a6c9d1e4b7
Create Date: 2026-08-18 20:00:00.000000+00:00

`app.workflows.defaults._build_graph`'s `planning` node now seeds
`config: {"allow_followup_question": False}` for every asset-kind
(`character`/`scene`/`cover`) graph — that generic clarify step runs before
`asset_planning` and has no idea `asset_kind`/`character_view` exist, so it
judges a bare completion-job prompt (e.g. just a character's name, see
`character-library.tsx`'s "补全侧面/背面") as missing scene/action/shot info
and asks for exactly what a character/scene/cover asset must NOT have (see
`app.agents.planner._ASSET_KIND_BRIEF`) — suspending the job at
`AWAITING_INPUT` with no way for the image studio to surface or answer it
(it never renders `AwaitingInputPanel`, unlike the standalone job page).

That code change only affects graphs seeded from here on
(`ensure_default_templates` never re-seeds a bucket that already has an
active template) — every `(operation, asset_kind)` template a database
already accumulated still carries the old `planning.config: {}` and would
keep reproducing the bug. This is the one-time backfill: for every active,
asset-kind-scoped `generation_workflow_templates` row, patch its
`graph_json.nodes[].config` for the node whose `id == "planning"` in place
(same "rewrite the row directly, no new version" precedent as
`20260809_2000_bind_workflow_agents_by_id.py`/
`20260816_0900_merge_image_workflow_templates.py` — these rows are
auto-seeded, not an operator's hand-edited history worth preserving).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa

from alembic import op

revision: str = "a9d4c7e2f8b1"
down_revision: str | None = "f2a6c9d1e4b7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    _rewrite_graphs(disable=True)


def downgrade() -> None:
    # Whether a row's `planning.config.allow_followup_question` was `False`
    # by an operator's own deliberate choice before this migration ran is not
    # recorded anywhere, so there is nothing sound to restore per row —
    # downgrading just re-enables it everywhere this migration touched.
    _rewrite_graphs(disable=False)


def _rewrite_graphs(*, disable: bool) -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT id, graph_json FROM generation_workflow_templates "
            "WHERE is_active = true AND asset_kind IS NOT NULL"
        )
    ).all()

    for template_id, graph_json in rows:
        graph = _as_dict(graph_json)
        if graph is None:
            continue
        changed = False
        for node in graph.get("nodes") or []:
            if isinstance(node, dict) and _rewrite_node(node, disable=disable):
                changed = True
        if changed:
            bind.execute(
                sa.text(
                    "UPDATE generation_workflow_templates "
                    "SET graph_json = CAST(:graph AS jsonb) WHERE id = :id"
                ),
                {"graph": json.dumps(graph), "id": template_id},
            )


def _rewrite_node(node: dict[str, Any], *, disable: bool) -> bool:
    if node.get("id") != "planning":
        return False
    config = node.setdefault("config", {})
    if not isinstance(config, dict):
        return False
    target = False if disable else True
    if config.get("allow_followup_question") is target:
        return False
    config["allow_followup_question"] = target
    return True


def _as_dict(raw: Any) -> dict[str, Any] | None:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except ValueError:
            return None
        return parsed if isinstance(parsed, dict) else None
    return None
