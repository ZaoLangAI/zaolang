"""asset entry camera pose (AC-2)

`skill_asset_entries.camera_json`: the camera pose a multi-angle image was
drawn from — `{azimuth, elevation, distance}` on the grid in
`app.domain.image_assets.camera`. Nullable: every existing entry (and any
upload the owner does not tag) has none; readers fall back to the coarse
`view` (`camera.from_view`).

Revision ID: 5b7e2c4a9d10
Revises: 83f620e021b1
Create Date: 2026-10-07 10:00:00+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "5b7e2c4a9d10"
down_revision: str | None = "83f620e021b1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "skill_asset_entries",
        sa.Column("camera_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("skill_asset_entries", "camera_json")
