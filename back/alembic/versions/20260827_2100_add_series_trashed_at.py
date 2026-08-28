"""add series trashed at

Revision ID: 899ea8654304
Revises: eb32862a35f4
Create Date: 2026-08-27 21:00:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "899ea8654304"
down_revision: str | None = "eb32862a35f4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("series", sa.Column("trashed_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("series", "trashed_at")
