"""add the 白膜 blockout: episode target duration, head document, version history

Revision ID: c9e4a7d2f1b8
Revises: b3d8f1a6c4e2
Create Date: 2026-09-24 12:00:00.000000+00:00

`drama_episodes.blocking_json` is the head blockout document and
`episode_blocking_versions` its history (`app.domain.blocking`).
`episode_script_turns.origin` tells a 文案 chat turn from a 白膜 chat turn,
since a 白膜 turn may rewrite the script as well.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "c9e4a7d2f1b8"
down_revision: str | None = "b3d8f1a6c4e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "drama_episodes", sa.Column("target_duration_seconds", sa.Integer(), nullable=True)
    )
    op.add_column(
        "drama_episodes",
        sa.Column(
            "blocking_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "episode_script_turns",
        sa.Column("origin", sa.String(length=16), server_default="script", nullable=False),
    )
    op.create_table(
        "episode_blocking_versions",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("episode_id", sa.String(length=40), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("origin", sa.String(length=16), nullable=False),
        sa.Column("turn_id", sa.String(length=40), nullable=True),
        sa.Column("user_id", sa.String(length=40), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("blocking_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("script_hash", sa.String(length=64), nullable=False),
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
            name=op.f("fk_episode_blocking_versions_episode_id_drama_episodes"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["turn_id"],
            ["episode_script_turns.id"],
            name=op.f("fk_episode_blocking_versions_turn_id_episode_script_turns"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_episode_blocking_versions_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_episode_blocking_versions")),
        sa.UniqueConstraint(
            "episode_id",
            "version_no",
            name=op.f("uq_episode_blocking_versions_episode_version"),
        ),
    )
    op.create_index(
        "ix_episode_blocking_versions_episode_id", "episode_blocking_versions", ["episode_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_episode_blocking_versions_episode_id", table_name="episode_blocking_versions")
    op.drop_table("episode_blocking_versions")
    op.drop_column("episode_script_turns", "origin")
    op.drop_column("drama_episodes", "blocking_json")
    op.drop_column("drama_episodes", "target_duration_seconds")
