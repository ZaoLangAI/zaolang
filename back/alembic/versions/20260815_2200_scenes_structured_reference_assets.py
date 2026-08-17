"""scenes: structured reference assets

Replaces `scenes.reference_asset_ids_json` (a flat list of asset ids) with
`reference_assets_json`, a list of `{"asset_id", "view", "label",
"created_at"}` entries — the same shape a character skill's reference assets
use (`app.domain.characters.service`), so a per-image view tag and label are
tracked instead of an anonymous id. See `app.models.scenes.Scene` and
`app.domain.scenes.service`.

Revision ID: a6b3d0f9c2e7
Revises: e2f5a8b3c7d1
Create Date: 2026-08-15 22:00:00.000000+00:00
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a6b3d0f9c2e7"
down_revision: str | None = "e2f5a8b3c7d1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "scenes",
        sa.Column(
            "reference_assets_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    bind = op.get_bind()
    rows = bind.execute(
        sa.text("SELECT id, reference_asset_ids_json, created_at FROM scenes")
    ).mappings().all()
    for row in rows:
        asset_ids = _as_list(row["reference_asset_ids_json"])
        created_at_iso = row["created_at"].isoformat() if row["created_at"] else None
        entries = [
            {"asset_id": asset_id, "view": "general", "label": None, "created_at": created_at_iso}
            for asset_id in asset_ids
        ]
        bind.execute(
            sa.text(
                "UPDATE scenes SET reference_assets_json = CAST(:entries AS jsonb) WHERE id = :id"
            ),
            {"entries": json.dumps(entries), "id": row["id"]},
        )
    op.alter_column(
        "scenes",
        "reference_assets_json",
        nullable=False,
        server_default=sa.text("'[]'::jsonb"),
    )
    op.alter_column("scenes", "reference_assets_json", server_default=None)
    op.drop_column("scenes", "reference_asset_ids_json")


def downgrade() -> None:
    op.add_column(
        "scenes",
        sa.Column(
            "reference_asset_ids_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id, reference_assets_json FROM scenes")).mappings().all()
    for row in rows:
        entries = _as_list(row["reference_assets_json"])
        asset_ids = [
            entry.get("asset_id")
            for entry in entries
            if isinstance(entry, dict) and entry.get("asset_id")
        ]
        bind.execute(
            sa.text(
                "UPDATE scenes SET reference_asset_ids_json = CAST(:ids AS jsonb) WHERE id = :id"
            ),
            {"ids": json.dumps(asset_ids), "id": row["id"]},
        )
    op.alter_column(
        "scenes",
        "reference_asset_ids_json",
        nullable=False,
        server_default=sa.text("'[]'::jsonb"),
    )
    op.alter_column("scenes", "reference_asset_ids_json", server_default=None)
    op.drop_column("scenes", "reference_assets_json")


def _as_list(raw: Any) -> list[Any]:
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except ValueError:
            return []
        return parsed if isinstance(parsed, list) else []
    return []
