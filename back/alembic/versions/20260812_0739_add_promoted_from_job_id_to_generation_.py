"""add promoted_from_job_id to generation_jobs

Revision ID: 5bc23ff7e383
Revises: b2e99848e1ca
Create Date: 2026-08-12 07:39:17.727372+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '5bc23ff7e383'
down_revision: str | None = 'b2e99848e1ca'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Autogenerate also flagged pre-existing server_default drift on unrelated
    # columns (agent_nodes.category, agent_profiles.media_candidates_json,
    # provider_async_tasks.*) — trimmed, not part of this change.
    op.add_column(
        'generation_jobs',
        sa.Column('promoted_from_job_id', sa.String(length=40), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('generation_jobs', 'promoted_from_job_id')
