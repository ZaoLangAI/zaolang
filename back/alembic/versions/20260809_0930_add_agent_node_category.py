"""add agent node category

Revision ID: 1c9f2ad4b731
Revises: 7b1c4a5e9d02
Create Date: 2026-08-09 09:30:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "1c9f2ad4b731"
down_revision: str | None = "7b1c4a5e9d02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The creative roles in `app.domain.agent_skills.presets` at the time of this
# migration. Inlined rather than imported so a later edit to the catalogue
# cannot retroactively change what this migration did. Every other existing
# row is a judgment role, which is also the column default.
_CREATIVE_ROLES: tuple[str, ...] = ("image_creative", "video_creative", "audio_creative")


def upgrade() -> None:
    op.add_column(
        "agent_nodes",
        sa.Column(
            "category", sa.String(length=20), nullable=False, server_default="judgment"
        ),
    )
    op.execute(
        sa.text("UPDATE agent_nodes SET category = 'creative' WHERE role = ANY(:roles)").bindparams(
            sa.bindparam("roles", value=list(_CREATIVE_ROLES), type_=sa.ARRAY(sa.String))
        )
    )
    # The default only existed to backfill existing rows; the model supplies it
    # for new ones, so leaving it in the schema would show up as drift.
    op.alter_column("agent_nodes", "category", server_default=None)


def downgrade() -> None:
    op.drop_column("agent_nodes", "category")
