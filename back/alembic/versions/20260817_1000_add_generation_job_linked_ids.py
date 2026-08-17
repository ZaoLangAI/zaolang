"""add generation_jobs.linked_character_id/linked_scene_id

Revision ID: f2a6c9d1e4b7
Revises: e7f1a4b8c3d6
Create Date: 2026-08-17 10:00:00.000000+00:00

Records which character/scene skill `app.workflows.nodes.execute_asset_output_link`
actually attached a succeeded job's output to — the target the client passed
in, or the id of a skill it auto-created. Nullable, no backfill: every
existing job predates the column and simply has both as `None`. Plain
strings, not FK-checked (matching `output_work_version_id`'s style), and at
most one of the two is ever set per job since `asset_kind` is never both at
once. Lets a client (the script studio's "返回文案创作" jump-back) learn
which card a job landed on without re-deriving it.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f2a6c9d1e4b7"
down_revision: str | None = "e7f1a4b8c3d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "generation_jobs",
        sa.Column("linked_character_id", sa.String(length=40), nullable=True),
    )
    op.add_column(
        "generation_jobs",
        sa.Column("linked_scene_id", sa.String(length=40), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("generation_jobs", "linked_scene_id")
    op.drop_column("generation_jobs", "linked_character_id")
