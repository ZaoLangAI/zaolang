"""add work appeals and work hide_reason

Revision ID: b3e1f6a9c2d4
Revises: a7b8c9d0e1f2
Create Date: 2026-08-14 09:00:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b3e1f6a9c2d4"
down_revision: str | None = "a7b8c9d0e1f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("works", sa.Column("hide_reason", sa.Text(), nullable=True))

    op.create_table(
        "work_appeals",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("work_id", sa.String(length=40), nullable=False),
        sa.Column("owner_user_id", sa.String(length=40), nullable=False),
        sa.Column("source_report_id", sa.String(length=40), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column("decided_by_user_id", sa.String(length=40), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["work_id"], ["works.id"], name=op.f("fk_work_appeals_work_id_works"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            name=op.f("fk_work_appeals_owner_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_report_id"],
            ["report_cases.id"],
            name=op.f("fk_work_appeals_source_report_id_report_cases"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["decided_by_user_id"],
            ["users.id"],
            name=op.f("fk_work_appeals_decided_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_work_appeals")),
    )
    op.create_index(
        "ix_work_appeals_status_created", "work_appeals", ["status", "created_at"], unique=False
    )
    op.create_index("ix_work_appeals_work_id", "work_appeals", ["work_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_work_appeals_work_id", table_name="work_appeals")
    op.drop_index("ix_work_appeals_status_created", table_name="work_appeals")
    op.drop_table("work_appeals")
    op.drop_column("works", "hide_reason")
