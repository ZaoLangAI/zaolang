"""add draft publish status

Nullable status plus a JSON snapshot of the publish form so the HTTP
accept can return before the pre-publish safety review runs.

Revision ID: a3f8c2d91e04
Revises: c7e2a91b04d8
Create Date: 2026-08-29 02:30:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a3f8c2d91e04"
down_revision: str | None = "c7e2a91b04d8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("drafts", sa.Column("publish_status", sa.String(length=20), nullable=True))
    op.add_column(
        "drafts",
        sa.Column(
            "publish_params_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column("drafts", sa.Column("publish_failure_message", sa.Text(), nullable=True))
    op.create_index("ix_drafts_publish_status", "drafts", ["publish_status"])


def downgrade() -> None:
    op.drop_index("ix_drafts_publish_status", table_name="drafts")
    op.drop_column("drafts", "publish_failure_message")
    op.drop_column("drafts", "publish_params_json")
    op.drop_column("drafts", "publish_status")
