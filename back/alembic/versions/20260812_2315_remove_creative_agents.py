"""remove creative agents and media candidates

Revision ID: bc896d6a4045
Revises: 861fbace3b82
Create Date: 2026-08-12 23:15:00.000000+00:00
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "bc896d6a4045"
down_revision: str | None = "861fbace3b82"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The three creative roles `app.domain.agent_skills.presets.ROLE_PRESETS` used
# to declare. Inlined rather than imported so a later edit to the catalogue
# cannot retroactively change what this migration did — the same reasoning
# `20260809_0930_add_agent_node_category.py` used to introduce them.
_CREATIVE_ROLES: tuple[str, ...] = ("image_creative", "video_creative", "audio_creative")

# `route_score`'s `CategoryAgentBinding` config field, dropped along with the
# category it selected by. Any stored graph (active or not, since versions
# are kept for rollback) that still names it must lose the reference before
# the column and the roles it pointed at disappear underneath it.
_CREATIVE_CONFIG_FIELD = "creative_agent_id"


def upgrade() -> None:
    _strip_creative_bindings()
    # `AgentSkill.profile_id` cascades at the database level, so deleting the
    # profiles below takes every prompt version they ever published with
    # them. `AgentNode.role` is not a foreign key (see its model docstring),
    # so node rows are removed independently, in no particular order.
    op.execute(
        sa.text("DELETE FROM agent_profiles WHERE role = ANY(:roles)").bindparams(
            sa.bindparam("roles", value=list(_CREATIVE_ROLES), type_=sa.ARRAY(sa.String))
        )
    )
    op.execute(
        sa.text("DELETE FROM agent_nodes WHERE role = ANY(:roles)").bindparams(
            sa.bindparam("roles", value=list(_CREATIVE_ROLES), type_=sa.ARRAY(sa.String))
        )
    )
    op.drop_column("agent_profiles", "media_candidates_json")


def downgrade() -> None:
    # Only the column comes back empty: the deleted creative agents, their
    # published prompts, and the `creative_agent_id` bindings stripped out of
    # every stored graph are not reconstructable, the same one-way trade-off
    # `bind_workflow_agents_by_id`'s `_move` accepts for a value it cannot
    # resolve. A fresh install (or one that never built a creative agent)
    # loses nothing by downgrading.
    op.add_column(
        "agent_profiles",
        sa.Column(
            "media_candidates_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.alter_column("agent_profiles", "media_candidates_json", server_default=None)


def _strip_creative_bindings() -> None:
    bind = op.get_bind()
    templates = bind.execute(
        sa.text("SELECT id, graph_json FROM generation_workflow_templates")
    ).all()
    for template_id, graph_json in templates:
        graph = _as_dict(graph_json)
        if graph is None:
            continue
        changed = False
        for node in graph.get("nodes") or []:
            config = node.get("config") if isinstance(node, dict) else None
            if isinstance(config, dict) and config.pop(_CREATIVE_CONFIG_FIELD, None) is not None:
                changed = True
        if changed:
            bind.execute(
                sa.text(
                    "UPDATE generation_workflow_templates "
                    "SET graph_json = CAST(:graph AS jsonb) WHERE id = :id"
                ),
                {"graph": json.dumps(graph), "id": template_id},
            )


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
