"""extend the creation-notification unique index to scripts and drafts

Revision ID: 4b5dd8d301c2
Revises: c9e4a7d2f1b8
Create Date: 2026-09-27 10:00:00.000000+00:00

`sync_creation_notification` upserts one row per `(user, target_type,
target_id)` for `episode_script` and `draft` too, but the partial unique index
only covered `generation_job`/`editor_export`, so two racing upserts on a
script or draft could each insert a row. Collapse any such duplicates to the
most recently updated row, then rebuild the index over all four target types.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "4b5dd8d301c2"
down_revision: str | None = "c9e4a7d2f1b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX = "uq_notifications_user_creation_target"
_OLD_WHERE = "target_type IN ('generation_job', 'editor_export') AND target_id IS NOT NULL"
_NEW_WHERE = (
    "target_type IN ('generation_job', 'editor_export', 'episode_script', 'draft') "
    "AND target_id IS NOT NULL"
)


def upgrade() -> None:
    op.execute(
        """
        DELETE FROM notifications a
        USING notifications b
        WHERE a.target_type IN ('episode_script', 'draft')
          AND a.target_id IS NOT NULL
          AND a.user_id = b.user_id
          AND a.target_type = b.target_type
          AND a.target_id = b.target_id
          AND (a.updated_at, a.id) < (b.updated_at, b.id)
        """
    )
    op.drop_index(_INDEX, table_name="notifications")
    op.create_index(
        _INDEX,
        "notifications",
        ["user_id", "target_type", "target_id"],
        unique=True,
        postgresql_where=sa.text(_NEW_WHERE),
    )


def downgrade() -> None:
    op.drop_index(_INDEX, table_name="notifications")
    op.create_index(
        _INDEX,
        "notifications",
        ["user_id", "target_type", "target_id"],
        unique=True,
        postgresql_where=sa.text(_OLD_WHERE),
    )
