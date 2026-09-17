"""add partial unique index enforcing one active editor lease per cut

Revision ID: c4f2a8b1d6e9
Revises: b3e1f6a9c2d4
Create Date: 2026-08-14 14:00:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c4f2a8b1d6e9"
down_revision: str | None = "b3e1f6a9c2d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "uq_editor_leases_active_cut",
        "editor_leases",
        ["cut_id"],
        unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_editor_leases_active_cut", table_name="editor_leases")
