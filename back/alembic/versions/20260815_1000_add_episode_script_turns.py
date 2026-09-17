"""add episode script turns

Revision ID: b3d6e2f9c1a4
Revises: f7c5e1a4b9d3
Create Date: 2026-08-15 10:00:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "b3d6e2f9c1a4"
down_revision: str | None = "f7c5e1a4b9d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "episode_script_turns",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("episode_id", sa.String(length=40), nullable=False),
        sa.Column("turn_no", sa.Integer(), nullable=False),
        sa.Column("parent_turn_id", sa.String(length=40), nullable=True),
        sa.Column("user_id", sa.String(length=40), nullable=True),
        sa.Column("user_message", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column(
            "script_snapshot_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "referenced_skill_ids_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("agent_run_id", sa.String(length=40), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["episode_id"],
            ["drama_episodes.id"],
            name=op.f("fk_episode_script_turns_episode_id_drama_episodes"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["parent_turn_id"],
            ["episode_script_turns.id"],
            name=op.f("fk_episode_script_turns_parent_turn_id_episode_script_turns"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_episode_script_turns_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_episode_script_turns")),
        sa.UniqueConstraint(
            "episode_id", "turn_no", name=op.f("uq_episode_script_turns_episode_turn")
        ),
    )
    op.create_index(
        "ix_episode_script_turns_episode_id", "episode_script_turns", ["episode_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_episode_script_turns_episode_id", table_name="episode_script_turns")
    op.drop_table("episode_script_turns")
