"""add provider async tasks

Revision ID: 3f5a71c0e9d8
Revises: 2d0e63bc84a5
Create Date: 2026-08-09 09:50:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "3f5a71c0e9d8"
down_revision: str | None = "2d0e63bc84a5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "provider_async_tasks",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("job_id", sa.String(length=40), nullable=False),
        sa.Column("node_id", sa.String(length=64), nullable=False),
        sa.Column("capability_name", sa.String(length=120), nullable=False),
        sa.Column("external_task_id", sa.String(length=200), nullable=False),
        sa.Column("request_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "state_checkpoint_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("provider_attempt_id", sa.String(length=40), nullable=True),
        sa.Column("next_poll_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("poll_count", sa.Integer(), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["generation_jobs.id"],
            name=op.f("fk_provider_async_tasks_job_id_generation_jobs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_provider_async_tasks")),
        # One in-flight external attempt per job: two would mean two branches
        # of one workflow are both waiting, which the runner cannot resume
        # coherently.
        sa.UniqueConstraint("job_id", name=op.f("uq_provider_async_tasks_job_id")),
    )
    op.create_index(
        "ix_provider_async_tasks_next_poll_at",
        "provider_async_tasks",
        ["next_poll_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_provider_async_tasks_next_poll_at", table_name="provider_async_tasks")
    op.drop_table("provider_async_tasks")
