"""add drama episode preview asset

Revision ID: c3d8a1b5e920
Revises: b8c4e6a2d710
Create Date: 2026-09-04 11:10:00.000000+00:00

Nullable FK on `drama_episodes.preview_asset_id` — the series roster
thumbnail (user upload or first frame of the episode's current video).
Same SET NULL pattern as `series.logo_asset_id`; existing rows stay
without a preview until upload or auto-extract fills them.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c3d8a1b5e920"
down_revision: str | None = "b8c4e6a2d710"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "drama_episodes",
        sa.Column("preview_asset_id", sa.String(length=40), nullable=True),
    )
    op.create_foreign_key(
        op.f("fk_drama_episodes_preview_asset_id_assets"),
        "drama_episodes",
        "assets",
        ["preview_asset_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_drama_episodes_preview_asset_id_assets"),
        "drama_episodes",
        type_="foreignkey",
    )
    op.drop_column("drama_episodes", "preview_asset_id")
