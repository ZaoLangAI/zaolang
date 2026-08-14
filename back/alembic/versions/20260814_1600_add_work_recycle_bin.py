"""add work recycle bin columns

Revision ID: e6b4d0f3a8c2
Revises: d5a3c9e2f7b1
Create Date: 2026-08-14 16:00:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e6b4d0f3a8c2"
down_revision: str | None = "d5a3c9e2f7b1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("works", sa.Column("trashed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("works", sa.Column("visibility_before_trash", sa.String(length=24), nullable=True))


def downgrade() -> None:
    op.drop_column("works", "visibility_before_trash")
    op.drop_column("works", "trashed_at")
