"""look attributes and scene link (P3)

A character look (造型) gains free-text attributes beside its enumerated
presets — `attributes_json` `{outfit?, state?, scene_note?, custom[]}` — and
an optional link to one of the owner's scene cards (and a variant of it).
`presets_json` stays enumerated-only (a look: `age_stage`, `period`), so
the scene write-back and matrix matching on it are untouched.

Deleting the linked scene card or variant clears the link (SET NULL).

Revision ID: da909e5c6791
Revises: c047a99bb3a5
Create Date: 2026-10-06 10:00:00+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "da909e5c6791"
down_revision: str | None = "c047a99bb3a5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "skill_asset_variants",
        sa.Column(
            "attributes_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "skill_asset_variants", sa.Column("scene_skill_id", sa.String(length=40), nullable=True)
    )
    op.add_column(
        "skill_asset_variants", sa.Column("scene_variant_id", sa.String(length=40), nullable=True)
    )
    op.create_foreign_key(
        op.f("fk_skill_asset_variants_scene_skill_id_creation_skills"),
        "skill_asset_variants",
        "creation_skills",
        ["scene_skill_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        op.f("fk_skill_asset_variants_scene_variant_id_skill_asset_variants"),
        "skill_asset_variants",
        "skill_asset_variants",
        ["scene_variant_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        op.f("ck_skill_asset_variants_scene_link_look_only"),
        "skill_asset_variants",
        "kind = 'look' OR (scene_skill_id IS NULL AND scene_variant_id IS NULL)",
    )
    op.create_index(
        "ix_skill_asset_variants_scene_skill_id", "skill_asset_variants", ["scene_skill_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_skill_asset_variants_scene_skill_id", table_name="skill_asset_variants")
    op.drop_constraint(
        op.f("ck_skill_asset_variants_scene_link_look_only"),
        "skill_asset_variants",
        type_="check",
    )
    op.drop_constraint(
        op.f("fk_skill_asset_variants_scene_variant_id_skill_asset_variants"),
        "skill_asset_variants",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_skill_asset_variants_scene_skill_id_creation_skills"),
        "skill_asset_variants",
        type_="foreignkey",
    )
    op.drop_column("skill_asset_variants", "scene_variant_id")
    op.drop_column("skill_asset_variants", "scene_skill_id")
    op.drop_column("skill_asset_variants", "attributes_json")
