"""asset entry consistency score (P3-2)

`skill_asset_entries.consistency_json`: the vision consistency judge's
verdict for a generated image against its card's anchor
(`app.domain.image_assets.consistency`), plus how the write-back applied it
(mode, threshold, whether it was demoted) and when the owner approved a
low-scoring one. Owner-only, never copied to another entry. Nullable and
add-only: existing entries were never scored.

Revision ID: def2867d63c8
Revises: 3e9a7c5d1f20
Create Date: 2026-10-08 11:00:00+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "def2867d63c8"
down_revision: str | None = "3e9a7c5d1f20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "skill_asset_entries",
        sa.Column("consistency_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("skill_asset_entries", "consistency_json")
