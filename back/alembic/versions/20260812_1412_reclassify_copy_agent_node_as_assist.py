"""reclassify copy agent node as assist

Revision ID: 861fbace3b82
Revises: 2c39f9f7a4ea
Create Date: 2026-08-12 14:12:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "861fbace3b82"
down_revision: str | None = "2c39f9f7a4ea"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# `AgentNodeView` prefers an `agent_nodes` row's own stored `category` over
# the live preset (`app.domain.agent_skills.presets`), so a role whose preset
# category changes after its node row was seeded needs its stored value
# backfilled too — code alone would leave every existing install showing
# "judgment" for `copy` forever.


def upgrade() -> None:
    op.execute(sa.text("UPDATE agent_nodes SET category = 'assist' WHERE role = 'copy'"))


def downgrade() -> None:
    op.execute(sa.text("UPDATE agent_nodes SET category = 'judgment' WHERE role = 'copy'"))
