"""add creation skill applicable operations

Revision ID: f1a2c3d4e5f6
Revises: e8b3b018ecfc
Create Date: 2026-08-13 12:00:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "f1a2c3d4e5f6"
down_revision: str | None = "e8b3b018ecfc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "creation_skills",
        sa.Column(
            "applicable_operations_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    # Backfill only; the model supplies the default for new rows.
    op.alter_column("creation_skills", "applicable_operations_json", server_default=None)


def downgrade() -> None:
    op.drop_column("creation_skills", "applicable_operations_json")
