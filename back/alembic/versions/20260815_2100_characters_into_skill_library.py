"""fold characters into the skill library

A character is no longer its own table: it becomes a `CreationSkill` with
`category='character'` (see `app.domain.characters.service`), so it gets the
skill library's draft/review/publish/marketplace lifecycle. Every character
row keeps its original id — `Series.character_ids_json` and
`ScriptCharacter.character_ref_id` (a plain string carried inside
`drama_episodes.script_json` / `episode_script_turns.script_snapshot_json`)
both just hold that id, and neither is a foreign key, so nothing downstream
needs rewriting: the same id now resolves against `creation_skills` instead
of `characters`.

Revision ID: e2f5a8b3c7d1
Revises: d9e4f7a2b6c3
Create Date: 2026-08-15 21:00:00.000000+00:00
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e2f5a8b3c7d1"
down_revision: str | None = "d9e4f7a2b6c3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHARACTER_CATEGORY = "character"


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT id, owner_user_id, name, description, reference_asset_ids_json, "
            "voice_description, created_at, updated_at FROM characters"
        )
    ).mappings().all()

    for row in rows:
        description = (row["description"] or "").strip() or None
        reference_ids = _as_list(row["reference_asset_ids_json"])
        created_at_iso = row["created_at"].isoformat() if row["created_at"] else None
        params_json = {
            "character": {
                "description": description,
                "voice_description": (row["voice_description"] or "").strip() or None,
                "reference_assets": [
                    {
                        "asset_id": asset_id,
                        "view": "general",
                        "label": None,
                        "created_at": created_at_iso,
                    }
                    for asset_id in reference_ids
                ],
            }
        }
        bind.execute(
            sa.text(
                "INSERT INTO creation_skills "
                "(id, owner_user_id, title, description, category, params_json, "
                "applicable_operations_json, cover_asset_id, visibility, status, "
                "usage_count, access_credits, reject_reason, reviewed_by_user_id, "
                "reviewed_at, created_at, updated_at) "
                "VALUES (:id, :owner_user_id, :title, :description, :category, "
                "CAST(:params_json AS jsonb), CAST(:applicable_operations_json AS jsonb), "
                "NULL, 'private', 'draft', 0, 0, NULL, NULL, NULL, :created_at, :updated_at)"
            ),
            {
                "id": row["id"],
                "owner_user_id": row["owner_user_id"],
                "title": (row["name"] or "")[:80],
                "description": (description or "")[:300],
                "category": _CHARACTER_CATEGORY,
                "params_json": json.dumps(params_json),
                "applicable_operations_json": json.dumps(["text_to_image", "image_to_image"]),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            },
        )

    op.drop_index("ix_characters_owner_user_id", table_name="characters")
    op.drop_table("characters")


def downgrade() -> None:
    op.create_table(
        "characters",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("owner_user_id", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "reference_asset_ids_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("voice_description", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            name=op.f("fk_characters_owner_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_characters")),
    )
    op.create_index("ix_characters_owner_user_id", "characters", ["owner_user_id"], unique=False)

    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT id, owner_user_id, title, params_json, created_at, updated_at "
            "FROM creation_skills WHERE category = :category"
        ).bindparams(category=_CHARACTER_CATEGORY)
    ).mappings().all()
    for row in rows:
        payload = _character_payload(row["params_json"])
        reference_ids = [
            entry.get("asset_id")
            for entry in payload.get("reference_assets") or []
            if isinstance(entry, dict) and entry.get("asset_id")
        ]
        bind.execute(
            sa.text(
                "INSERT INTO characters "
                "(id, owner_user_id, name, description, reference_asset_ids_json, "
                "voice_description, created_at, updated_at) "
                "VALUES (:id, :owner_user_id, :name, :description, "
                "CAST(:reference_asset_ids_json AS jsonb), :voice_description, "
                ":created_at, :updated_at)"
            ),
            {
                "id": row["id"],
                "owner_user_id": row["owner_user_id"],
                "name": row["title"],
                "description": payload.get("description"),
                "reference_asset_ids_json": json.dumps(reference_ids),
                "voice_description": payload.get("voice_description"),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            },
        )
    op.execute(
        sa.text("DELETE FROM creation_skills WHERE category = :category").bindparams(
            category=_CHARACTER_CATEGORY
        )
    )


def _as_list(raw: Any) -> list[str]:
    if isinstance(raw, list):
        return [str(item) for item in raw]
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except ValueError:
            return []
        return [str(item) for item in parsed] if isinstance(parsed, list) else []
    return []


def _character_payload(raw: Any) -> dict[str, Any]:
    parsed = raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except ValueError:
            parsed = {}
    if not isinstance(parsed, dict):
        return {}
    payload = parsed.get("character")
    return payload if isinstance(payload, dict) else {}
