"""bind workflow agent nodes by agent id

Revision ID: 5b2c8e14a7f3
Revises: 3f5a71c0e9d8
Create Date: 2026-08-09 20:00:00.000000+00:00
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa

from alembic import op

revision: str = "5b2c8e14a7f3"
down_revision: str | None = "3f5a71c0e9d8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Workflow nodes used to name an agent by `(role, key)`, where the role came
# from the node type and the key sat in the config. They now name it by id, so
# every stored graph needs its keys resolved once.
#
# The node-type table is inlined rather than imported from
# `app.workflows.registry`: a later edit to the registry must not retroactively
# change what this migration did. `custom_agent` is absent because its role is
# in the config (`agent_role`), handled separately below.
_RENAMES: dict[str, tuple[str, str, str]] = {
    # node type -> (old config field, new config field, role)
    "safety_check": ("agent_profile", "agent_id", "safety"),
    "planning": ("agent_profile", "agent_id", "planner"),
    "intent_router": ("agent_profile", "agent_id", "intent_router"),
    "quality_check": ("agent_profile", "agent_id", "quality"),
    "route_score": ("selector_profile", "selector_agent_id", "intent_router"),
}

_CUSTOM_AGENT_TYPE = "custom_agent"

# Already an id; only the name changes, to match the fields above.
_CREATIVE_RENAME = ("creative_profile_id", "creative_agent_id")


class _AgentIndex:
    """Both directions of the `(role, key)` <-> id mapping, read once."""

    def __init__(self, rows: Sequence[tuple[str, str, str]]) -> None:
        self._by_key = {(role, key): agent_id for agent_id, role, key in rows}
        self._by_id = {agent_id: (role, key) for agent_id, role, key in rows}

    def id_for(self, role: str, key: str) -> str | None:
        return self._by_key.get((role, key))

    def key_for(self, role: str, agent_id: str) -> str | None:
        found = self._by_id.get(agent_id)
        return found[1] if found is not None and found[0] == role else None


def upgrade() -> None:
    _rewrite_graphs(forwards=True)


def downgrade() -> None:
    _rewrite_graphs(forwards=False)


def _rewrite_graphs(*, forwards: bool) -> None:
    bind = op.get_bind()
    agents = _agent_index(bind)
    templates = bind.execute(
        sa.text("SELECT id, graph_json FROM generation_workflow_templates")
    ).all()

    for template_id, graph_json in templates:
        graph = _as_dict(graph_json)
        if graph is None:
            continue
        changed = False
        for node in graph.get("nodes") or []:
            if isinstance(node, dict) and _rewrite_node(node, agents, forwards=forwards):
                changed = True
        if changed:
            bind.execute(
                sa.text(
                    "UPDATE generation_workflow_templates "
                    "SET graph_json = CAST(:graph AS jsonb) WHERE id = :id"
                ),
                {"graph": json.dumps(graph), "id": template_id},
            )


def _rewrite_node(node: dict[str, Any], agents: _AgentIndex, *, forwards: bool) -> bool:
    config = node.get("config")
    if not isinstance(config, dict):
        return False

    old_creative, new_creative = _CREATIVE_RENAME if forwards else _CREATIVE_RENAME[::-1]
    changed = _move(config, old_creative, new_creative, lambda value: value)

    node_type = node.get("type")
    rename = _RENAMES.get(str(node_type))
    if rename is not None:
        before, after, role = rename
    elif node_type == _CUSTOM_AGENT_TYPE:
        before, after = "agent_profile", "agent_id"
        role = str(config.get("agent_role", ""))
    else:
        return changed

    old_field, new_field = (before, after) if forwards else (after, before)
    resolve = agents.id_for if forwards else agents.key_for
    return _move(config, old_field, new_field, lambda value: resolve(role, value)) or changed


def _move(config: dict[str, Any], old_field: str, new_field: str, resolve: Any) -> bool:
    """Renames one config field, translating its value on the way.

    A value that cannot be translated is dropped rather than carried over: it
    already pointed at an agent that no longer exists, and an unresolvable
    binding falls back to the role's default at runtime anyway. Keeping it
    would instead block the next publish on a validation error the operator
    cannot act on.
    """
    if old_field not in config:
        return False
    raw = config.pop(old_field)
    if not isinstance(raw, str) or not raw.strip():
        return True
    translated = resolve(raw.strip())
    if translated:
        config[new_field] = translated
    return True


def _agent_index(bind: sa.Connection) -> _AgentIndex:
    rows = bind.execute(sa.text("SELECT id, role, key FROM agent_profiles")).all()
    return _AgentIndex([(row[0], row[1], row[2]) for row in rows])


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
