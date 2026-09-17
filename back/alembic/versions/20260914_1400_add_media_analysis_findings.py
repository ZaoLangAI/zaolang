"""add findings to media analyses for the post-export health check

Revision ID: f6b1d4a8c3e5
Revises: e5a9c3f1b7d2
Create Date: 2026-09-14 14:00:00.000000+00:00

The `export-qa` analyzer (`app.domain.editor.analysis.run_export_qa`) checks
a finished editor export for black frames, a frozen picture, long silence,
off-target loudness and clipping. Its hint-only findings need a home that
none of the existing transcript/shots/focus/audio columns describe.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "f6b1d4a8c3e5"
down_revision: str | None = "e5a9c3f1b7d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "media_analyses",
        sa.Column(
            "findings_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("media_analyses", "findings_json")
