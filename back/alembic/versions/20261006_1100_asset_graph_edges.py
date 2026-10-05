"""asset graph edges (P4)

Typed, directed relations between a card's looks / variants, or between its
images: `skill_asset_edges`. Each level has its own nullable source/target
pair with a composite FK `(x_id, skill_id)` — so both ends are on the same
card — that CASCADEs when either end (or the card) is deleted. Acyclicity is
enforced by the domain (`asset_graph.service.add_edge`, under a card row
lock), not the database.

Also adds `uq_skill_asset_entries_id_skill_id`, the target of the entry
pair's composite FK.

Revision ID: 0d4fcb01efea
Revises: da909e5c6791
Create Date: 2026-10-06 11:00:00+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0d4fcb01efea"
down_revision: str | None = "da909e5c6791"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LEVEL_SHAPE = (
    "(level = 'variant' AND source_variant_id IS NOT NULL AND target_variant_id IS NOT NULL"
    " AND source_entry_id IS NULL AND target_entry_id IS NULL"
    " AND source_variant_id <> target_variant_id)"
    " OR (level = 'entry' AND source_entry_id IS NOT NULL AND target_entry_id IS NOT NULL"
    " AND source_variant_id IS NULL AND target_variant_id IS NULL"
    " AND source_entry_id <> target_entry_id)"
)


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_skill_asset_entries_id_skill_id", "skill_asset_entries", ["id", "skill_id"]
    )
    op.create_table(
        "skill_asset_edges",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("skill_id", sa.String(length=40), nullable=False),
        sa.Column("level", sa.String(length=8), nullable=False),
        sa.Column("source_variant_id", sa.String(length=40), nullable=True),
        sa.Column("target_variant_id", sa.String(length=40), nullable=True),
        sa.Column("source_entry_id", sa.String(length=40), nullable=True),
        sa.Column("target_entry_id", sa.String(length=40), nullable=True),
        sa.Column(
            "relations_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("label", sa.String(length=40), nullable=True),
        sa.Column("origin", sa.String(length=8), nullable=False),
        sa.Column("source_job_id", sa.String(length=40), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint("level IN ('variant', 'entry')", name=op.f("ck_skill_asset_edges_level_valid")),
        sa.CheckConstraint("origin IN ('auto', 'manual')", name=op.f("ck_skill_asset_edges_origin_valid")),
        sa.CheckConstraint(LEVEL_SHAPE, name=op.f("ck_skill_asset_edges_level_shape")),
        sa.ForeignKeyConstraint(
            ["skill_id"],
            ["creation_skills.id"],
            name=op.f("fk_skill_asset_edges_skill_id_creation_skills"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_variant_id", "skill_id"],
            ["skill_asset_variants.id", "skill_asset_variants.skill_id"],
            name="fk_skill_asset_edges_source_variant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["target_variant_id", "skill_id"],
            ["skill_asset_variants.id", "skill_asset_variants.skill_id"],
            name="fk_skill_asset_edges_target_variant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_entry_id", "skill_id"],
            ["skill_asset_entries.id", "skill_asset_entries.skill_id"],
            name="fk_skill_asset_edges_source_entry",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["target_entry_id", "skill_id"],
            ["skill_asset_entries.id", "skill_asset_entries.skill_id"],
            name="fk_skill_asset_edges_target_entry",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_skill_asset_edges")),
    )
    op.create_index("ix_skill_asset_edges_skill_level", "skill_asset_edges", ["skill_id", "level"])
    op.create_index(
        "uq_skill_asset_edges_variant_pair",
        "skill_asset_edges",
        ["source_variant_id", "target_variant_id"],
        unique=True,
        postgresql_where=sa.text("level = 'variant'"),
    )
    op.create_index(
        "uq_skill_asset_edges_entry_pair",
        "skill_asset_edges",
        ["source_entry_id", "target_entry_id"],
        unique=True,
        postgresql_where=sa.text("level = 'entry'"),
    )


def downgrade() -> None:
    op.drop_index("uq_skill_asset_edges_entry_pair", table_name="skill_asset_edges")
    op.drop_index("uq_skill_asset_edges_variant_pair", table_name="skill_asset_edges")
    op.drop_index("ix_skill_asset_edges_skill_level", table_name="skill_asset_edges")
    op.drop_table("skill_asset_edges")
    op.drop_constraint(
        "uq_skill_asset_entries_id_skill_id", "skill_asset_entries", type_="unique"
    )
