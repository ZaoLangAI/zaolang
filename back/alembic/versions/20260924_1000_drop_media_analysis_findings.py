"""drop the post-export health check's findings column

Revision ID: b3d8f1a6c4e2
Revises: a7c2e9f4b1d6
Create Date: 2026-09-24 10:00:00.000000+00:00

The `export-qa` analyzer was removed. Its rows are hint-only data derived
from an export file, so they are deleted rather than left behind — an
`export-qa` row would otherwise be the newest analysis for an exported
asset and stand in for that asset's own `ffprobe` analysis in
`analysis.summary_for`. `f6b1d4a8c3e5`, which added the column, stays in
the chain because production has already run it.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "b3d8f1a6c4e2"
down_revision: str | None = "a7c2e9f4b1d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DELETE FROM media_analyses WHERE analyzer = 'export-qa'")
    op.drop_column("media_analyses", "findings_json")


def downgrade() -> None:
    op.add_column(
        "media_analyses",
        sa.Column(
            "findings_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
