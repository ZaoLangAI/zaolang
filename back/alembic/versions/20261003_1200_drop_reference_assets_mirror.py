"""drop the reference_assets JSON mirror (P2-8, P1-4's migration B)

P1 kept `params_json[character|scene]["reference_assets"]` as a write-through
mirror of the looks / variants tables for one release. Every reader now uses
the tables (`asset_variants.service.project`), so the copy is removed.

The downgrade rebuilds the mirror from the tables in `project()`'s shape and
order — approved entries, the anchor first, then the default variant, the
others by `sort_order`, entries by `sort_order` — so rolling back to the
previous release (and on to the P1 migration's own downgrade) loses nothing.

Revision ID: c047a99bb3a5
Revises: d1a8a7ac68fd
Create Date: 2026-10-03 12:00:00+00:00
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa

from alembic import op

revision: str = "c047a99bb3a5"
down_revision: str | None = "d1a8a7ac68fd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MIRROR_KEY = {"character": "character", "scene_asset": "scene"}


def projected_view(category: str, entry_type: str, view: str | None) -> str:
    """`asset_variants.service._projected_view`, frozen here."""
    if category == "character":
        if entry_type == "character_sheet":
            return "front"
        if entry_type == "view" and view:
            return view
        return "general"
    if entry_type == "master":
        return "establishing"
    return view or "general"


def project_rows(
    category: str, variants: list[dict[str, Any]], entries: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """The mirror list for one card from its variant and entry rows."""
    order = {
        v["id"]: (0 if v["is_default"] else 1, v["sort_order"], str(v["created_at"]))
        for v in variants
    }
    by_id = {v["id"]: v for v in variants}
    approved = [e for e in entries if e["status"] == "approved" and e["variant_id"] in by_id]
    approved.sort(
        key=lambda e: (
            0 if e["is_anchor"] else 1,
            order[e["variant_id"]],
            e["sort_order"],
            str(e["created_at"]),
        )
    )
    projected = []
    for entry in approved:
        variant = by_id[entry["variant_id"]]
        projected.append(
            {
                "asset_id": entry["asset_id"],
                "view": projected_view(category, entry["entry_type"], entry["view"]),
                "label": entry["label"] if variant["is_default"] else variant["name"],
                "created_at": entry["created_at"].isoformat()
                if hasattr(entry["created_at"], "isoformat")
                else entry["created_at"],
            }
        )
    return projected


def upgrade() -> None:
    op.execute(
        "UPDATE creation_skills "
        "SET params_json = (params_json #- '{character,reference_assets}') "
        "#- '{scene,reference_assets}' "
        "WHERE category IN ('character', 'scene_asset')"
    )


def downgrade() -> None:
    bind = op.get_bind()
    skills = bind.execute(
        sa.text(
            "SELECT id, category, params_json FROM creation_skills "
            "WHERE category IN ('character', 'scene_asset')"
        )
    ).all()
    for skill in skills:
        variants = [
            dict(row._mapping)
            for row in bind.execute(
                sa.text(
                    "SELECT id, name, is_default, sort_order, created_at "
                    "FROM skill_asset_variants WHERE skill_id = :id"
                ),
                {"id": skill.id},
            )
        ]
        entries = [
            dict(row._mapping)
            for row in bind.execute(
                sa.text(
                    "SELECT variant_id, asset_id, entry_type, view, label, status, is_anchor, "
                    "sort_order, created_at FROM skill_asset_entries WHERE skill_id = :id"
                ),
                {"id": skill.id},
            )
        ]
        params = dict(skill.params_json or {})
        key = MIRROR_KEY[skill.category]
        nested = dict(params.get(key) or {})
        nested["reference_assets"] = project_rows(skill.category, variants, entries)
        params[key] = nested
        bind.execute(
            sa.text("UPDATE creation_skills SET params_json = CAST(:p AS JSONB) WHERE id = :id"),
            {"p": json.dumps(params, ensure_ascii=False), "id": skill.id},
        )
