"""add agent run thinking text

Relationship-adjacent trace column, not backfilled: existing runs simply
read back the empty-string default (see `AgentRun.thinking_text` in
`app.models.generation`).

Revision ID: c7e2a91b04d8
Revises: 865f5af713b7
Create Date: 2026-08-28 22:00:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c7e2a91b04d8"
down_revision: str | None = "865f5af713b7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_runs",
        sa.Column("thinking_text", sa.Text(), server_default="", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("agent_runs", "thinking_text")
