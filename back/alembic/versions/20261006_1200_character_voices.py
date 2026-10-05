"""character voices (P7)

`character_voices` (`chv`): a character card's voice profiles — a preset
voice of one TTS model with its parameters, or a clone sample — plus their
attributes, preview audio and one default per card. A look can be bound to
one voice (`skill_asset_variants.voice_id`, SET NULL; same card enforced by
the domain), and the relation graph gains a `voice` level whose pair FKs are
composite `(x_id, skill_id)` like the others.

Revision ID: 83f620e021b1
Revises: 0d4fcb01efea
Create Date: 2026-10-06 12:00:00+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "83f620e021b1"
down_revision: str | None = "0d4fcb01efea"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_SHAPE = (
    "(level = 'variant' AND source_variant_id IS NOT NULL AND target_variant_id IS NOT NULL"
    " AND source_entry_id IS NULL AND target_entry_id IS NULL"
    " AND source_variant_id <> target_variant_id)"
    " OR (level = 'entry' AND source_entry_id IS NOT NULL AND target_entry_id IS NOT NULL"
    " AND source_variant_id IS NULL AND target_variant_id IS NULL"
    " AND source_entry_id <> target_entry_id)"
)
NEW_SHAPE = (
    "(level = 'variant' AND source_variant_id IS NOT NULL AND target_variant_id IS NOT NULL"
    " AND source_entry_id IS NULL AND target_entry_id IS NULL"
    " AND source_voice_id IS NULL AND target_voice_id IS NULL"
    " AND source_variant_id <> target_variant_id)"
    " OR (level = 'entry' AND source_entry_id IS NOT NULL AND target_entry_id IS NOT NULL"
    " AND source_variant_id IS NULL AND target_variant_id IS NULL"
    " AND source_voice_id IS NULL AND target_voice_id IS NULL"
    " AND source_entry_id <> target_entry_id)"
    " OR (level = 'voice' AND source_voice_id IS NOT NULL AND target_voice_id IS NOT NULL"
    " AND source_variant_id IS NULL AND target_variant_id IS NULL"
    " AND source_entry_id IS NULL AND target_entry_id IS NULL"
    " AND source_voice_id <> target_voice_id)"
)


def upgrade() -> None:
    op.create_table(
        "character_voices",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("skill_id", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=40), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=8), nullable=False),
        sa.Column("model", sa.String(length=200), nullable=True),
        sa.Column("voice", sa.String(length=60), nullable=True),
        sa.Column(
            "params_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "attributes_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("sample_asset_id", sa.String(length=40), nullable=True),
        sa.Column("preview_asset_id", sa.String(length=40), nullable=True),
        sa.Column("preview_text", sa.String(length=200), nullable=True),
        sa.Column("preview_job_id", sa.String(length=40), nullable=True),
        sa.Column("is_default", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(
            "source IN ('preset', 'clone')", name=op.f("ck_character_voices_source_valid")
        ),
        sa.CheckConstraint(
            "source <> 'preset' OR (model IS NOT NULL AND voice IS NOT NULL)",
            name=op.f("ck_character_voices_preset_has_voice"),
        ),
        sa.ForeignKeyConstraint(
            ["skill_id"],
            ["creation_skills.id"],
            name=op.f("fk_character_voices_skill_id_creation_skills"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["sample_asset_id"],
            ["assets.id"],
            name=op.f("fk_character_voices_sample_asset_id_assets"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["preview_asset_id"],
            ["assets.id"],
            name=op.f("fk_character_voices_preview_asset_id_assets"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_character_voices")),
        sa.UniqueConstraint("skill_id", "name", name="uq_character_voices_skill_id_name"),
        sa.UniqueConstraint("id", "skill_id", name="uq_character_voices_id_skill_id"),
    )
    op.create_index("ix_character_voices_skill_id", "character_voices", ["skill_id"])
    op.create_index(
        "uq_character_voices_default",
        "character_voices",
        ["skill_id"],
        unique=True,
        postgresql_where=sa.text("is_default"),
    )

    op.add_column(
        "skill_asset_variants", sa.Column("voice_id", sa.String(length=40), nullable=True)
    )
    op.create_foreign_key(
        op.f("fk_skill_asset_variants_voice_id_character_voices"),
        "skill_asset_variants",
        "character_voices",
        ["voice_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        op.f("ck_skill_asset_variants_voice_look_only"),
        "skill_asset_variants",
        "kind = 'look' OR voice_id IS NULL",
    )

    op.add_column("skill_asset_edges", sa.Column("source_voice_id", sa.String(length=40)))
    op.add_column("skill_asset_edges", sa.Column("target_voice_id", sa.String(length=40)))
    op.create_foreign_key(
        "fk_skill_asset_edges_source_voice",
        "skill_asset_edges",
        "character_voices",
        ["source_voice_id", "skill_id"],
        ["id", "skill_id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_skill_asset_edges_target_voice",
        "skill_asset_edges",
        "character_voices",
        ["target_voice_id", "skill_id"],
        ["id", "skill_id"],
        ondelete="CASCADE",
    )
    op.drop_constraint(
        op.f("ck_skill_asset_edges_level_valid"), "skill_asset_edges", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_skill_asset_edges_level_valid"),
        "skill_asset_edges",
        "level IN ('variant', 'entry', 'voice')",
    )
    op.drop_constraint(
        op.f("ck_skill_asset_edges_level_shape"), "skill_asset_edges", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_skill_asset_edges_level_shape"), "skill_asset_edges", NEW_SHAPE
    )
    op.create_index(
        "uq_skill_asset_edges_voice_pair",
        "skill_asset_edges",
        ["source_voice_id", "target_voice_id"],
        unique=True,
        postgresql_where=sa.text("level = 'voice'"),
    )


def downgrade() -> None:
    op.execute("DELETE FROM skill_asset_edges WHERE level = 'voice'")
    op.drop_index("uq_skill_asset_edges_voice_pair", table_name="skill_asset_edges")
    op.drop_constraint(
        op.f("ck_skill_asset_edges_level_shape"), "skill_asset_edges", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_skill_asset_edges_level_shape"), "skill_asset_edges", OLD_SHAPE
    )
    op.drop_constraint(
        op.f("ck_skill_asset_edges_level_valid"), "skill_asset_edges", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_skill_asset_edges_level_valid"),
        "skill_asset_edges",
        "level IN ('variant', 'entry')",
    )
    op.drop_constraint("fk_skill_asset_edges_target_voice", "skill_asset_edges", type_="foreignkey")
    op.drop_constraint("fk_skill_asset_edges_source_voice", "skill_asset_edges", type_="foreignkey")
    op.drop_column("skill_asset_edges", "target_voice_id")
    op.drop_column("skill_asset_edges", "source_voice_id")
    op.drop_constraint(
        op.f("ck_skill_asset_variants_voice_look_only"), "skill_asset_variants", type_="check"
    )
    op.drop_constraint(
        op.f("fk_skill_asset_variants_voice_id_character_voices"),
        "skill_asset_variants",
        type_="foreignkey",
    )
    op.drop_column("skill_asset_variants", "voice_id")
    op.drop_index("uq_character_voices_default", table_name="character_voices")
    op.drop_index("ix_character_voices_skill_id", table_name="character_voices")
    op.drop_table("character_voices")
