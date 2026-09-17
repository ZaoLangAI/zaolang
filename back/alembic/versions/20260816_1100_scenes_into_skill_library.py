"""fold scenes into the skill library

A scene is no longer its own table: it becomes a `CreationSkill` with
`category='scene_asset'` (see `app.domain.scenes.service`), so it gets the
skill library's draft/review/publish/marketplace lifecycle — mirrors
`20260815_2100_characters_into_skill_library.py`'s treatment of characters.
Every scene row keeps its original id — `ScriptScene.ref_id` and
`GenerationParams.scene_ids`/`target_scene_id` are plain strings carried
inside JSON columns, not foreign keys, so nothing downstream needs
rewriting: the same id now resolves against `creation_skills` instead of
`scenes`.

`'scene_asset'` (not plain `'scene'`) because `'scene'` was already a
`CreationSkillCategory` value with an unrelated meaning — a shareable
"scene style" prompt template (`app.domain.skill_library`), unchanged by
this migration.

Revision ID: d4e8f1a5b9c2
Revises: c1d4e7f0a3b6
Create Date: 2026-08-16 11:00:00.000000+00:00
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d4e8f1a5b9c2"
down_revision: str | None = "c1d4e7f0a3b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCENE_ASSET_CATEGORY = "scene_asset"


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT id, owner_user_id, name, description, reference_assets_json, "
            "created_at, updated_at FROM scenes"
        )
    ).mappings().all()

    for row in rows:
        description = (row["description"] or "").strip() or None
        params_json = {
            "scene": {
                "description": description,
                "reference_assets": _as_entries(row["reference_assets_json"]),
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
                "category": _SCENE_ASSET_CATEGORY,
                "params_json": json.dumps(params_json),
                "applicable_operations_json": json.dumps(["text_to_image", "image_to_image"]),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            },
        )

    op.drop_index("ix_scenes_owner_user_id", table_name="scenes")
    op.drop_table("scenes")


def downgrade() -> None:
    op.create_table(
        "scenes",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("owner_user_id", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "reference_assets_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            name=op.f("fk_scenes_owner_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scenes")),
    )
    op.create_index("ix_scenes_owner_user_id", "scenes", ["owner_user_id"], unique=False)

    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT id, owner_user_id, title, params_json, created_at, updated_at "
            "FROM creation_skills WHERE category = :category"
        ).bindparams(category=_SCENE_ASSET_CATEGORY)
    ).mappings().all()
    for row in rows:
        payload = _scene_payload(row["params_json"])
        entries = [
            entry
            for entry in payload.get("reference_assets") or []
            if isinstance(entry, dict) and entry.get("asset_id")
        ]
        bind.execute(
            sa.text(
                "INSERT INTO scenes "
                "(id, owner_user_id, name, description, reference_assets_json, "
                "created_at, updated_at) "
                "VALUES (:id, :owner_user_id, :name, :description, "
                "CAST(:reference_assets_json AS jsonb), :created_at, :updated_at)"
            ),
            {
                "id": row["id"],
                "owner_user_id": row["owner_user_id"],
                "name": row["title"],
                "description": payload.get("description"),
                "reference_assets_json": json.dumps(entries),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            },
        )
    op.execute(
        sa.text("DELETE FROM creation_skills WHERE category = :category").bindparams(
            category=_SCENE_ASSET_CATEGORY
        )
    )


def _as_entries(raw: Any) -> list[dict[str, Any]]:
    parsed = raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except ValueError:
            return []
    if not isinstance(parsed, list):
        return []
    return [entry for entry in parsed if isinstance(entry, dict) and entry.get("asset_id")]


def _scene_payload(raw: Any) -> dict[str, Any]:
    parsed = raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except ValueError:
            parsed = {}
    if not isinstance(parsed, dict):
        return {}
    payload = parsed.get("scene")
    return payload if isinstance(payload, dict) else {}
