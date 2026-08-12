"""add job correlation columns to job_events, agent_runs, system_logs

Revision ID: 52b80f3f3f8f
Revises: 8a61d47c2f10
Create Date: 2026-08-11 19:30:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "52b80f3f3f8f"
down_revision: str | None = "8a61d47c2f10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("job_events", sa.Column("node_id", sa.String(length=64), nullable=True))
    op.add_column("agent_runs", sa.Column("node_id", sa.String(length=64), nullable=True))
    op.add_column("system_logs", sa.Column("job_id", sa.String(length=40), nullable=True))
    op.create_index(
        "ix_system_logs_job_id", "system_logs", ["job_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_system_logs_job_id", table_name="system_logs")
    op.drop_column("system_logs", "job_id")
    op.drop_column("agent_runs", "node_id")
    op.drop_column("job_events", "node_id")
