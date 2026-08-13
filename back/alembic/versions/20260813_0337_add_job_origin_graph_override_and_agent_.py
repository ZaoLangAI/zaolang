"""add job origin graph override and agent run input

Revision ID: e8b3b018ecfc
Revises: bc896d6a4045
Create Date: 2026-08-13 03:37:28.999615+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "e8b3b018ecfc"
down_revision: str | None = "bc896d6a4045"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Autogenerate also flagged pre-existing server_default drift on
    # agent_nodes.category and provider_async_tasks.* — trimmed, not part
    # of this change.
    op.add_column(
        "agent_runs",
        sa.Column("input_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "generation_jobs",
        sa.Column("origin", sa.String(length=24), server_default="user", nullable=False),
    )
    op.add_column(
        "generation_jobs",
        sa.Column(
            "graph_override_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("generation_jobs", "graph_override_json")
    op.drop_column("generation_jobs", "origin")
    op.drop_column("agent_runs", "input_json")
