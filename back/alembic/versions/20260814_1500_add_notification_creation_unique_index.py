"""add creation-notification unique index and backfill in-flight rows

Revision ID: d5a3c9e2f7b1
Revises: c4f2a8b1d6e9
Create Date: 2026-08-14 15:00:00.000000+00:00
"""

from __future__ import annotations

import json
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from app.models.base import new_id

revision: str = "d5a3c9e2f7b1"
down_revision: str | None = "c4f2a8b1d6e9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            DELETE FROM notifications a
            USING notifications b
            WHERE a.target_type IN ('generation_job', 'editor_export')
              AND a.target_id IS NOT NULL
              AND a.user_id = b.user_id
              AND a.target_type = b.target_type
              AND a.target_id = b.target_id
              AND a.id < b.id
            """
        )
    )

    jobs = conn.execute(
        sa.text(
            """
            SELECT id, user_id, status, operation
            FROM generation_jobs
            WHERE origin = 'user'
              AND status NOT IN ('succeeded', 'failed', 'cancelled', 'expired')
              AND NOT EXISTS (
                SELECT 1 FROM notifications n
                WHERE n.user_id = generation_jobs.user_id
                  AND n.target_type = 'generation_job'
                  AND n.target_id = generation_jobs.id
              )
            """
        )
    ).fetchall()
    for job in jobs:
        conn.execute(
            sa.text(
                """
                INSERT INTO notifications (
                    id, user_id, type, title_key, payload_json,
                    target_type, target_id, created_at, updated_at
                )
                VALUES (
                    :id, :user_id, 'job_progress', 'notification.job_queued',
                    CAST(:payload AS jsonb), 'generation_job', :target_id, NOW(), NOW()
                )
                """
            ),
            {
                "id": new_id("ntf"),
                "user_id": job.user_id,
                "payload": json.dumps(
                    {"job_id": job.id, "status": job.status, "operation": job.operation}
                ),
                "target_id": job.id,
            },
        )

    exports = conn.execute(
        sa.text(
            """
            SELECT id, status
            FROM editor_exports
            WHERE status NOT IN ('succeeded', 'failed', 'cancelled')
              AND NOT EXISTS (
                SELECT 1 FROM notifications n
                WHERE n.target_type = 'editor_export'
                  AND n.target_id = editor_exports.id
              )
            """
        )
    ).fetchall()
    for export in exports:
        owner = conn.execute(
            sa.text(
                """
                SELECT s.owner_user_id
                FROM editor_exports e
                JOIN delivery_variants v ON v.id = e.variant_id
                JOIN cut_revisions r ON r.id = v.cut_revision_id
                JOIN episode_cuts c ON c.id = r.cut_id
                JOIN drama_episodes ep ON ep.id = c.episode_id
                JOIN series s ON s.id = ep.series_id
                WHERE e.id = :export_id
                """
            ),
            {"export_id": export.id},
        ).scalar()
        if owner is None:
            continue
        conn.execute(
            sa.text(
                """
                INSERT INTO notifications (
                    id, user_id, type, title_key, payload_json,
                    target_type, target_id, created_at, updated_at
                )
                VALUES (
                    :id, :user_id, 'job_progress', 'notification.export_queued',
                    CAST(:payload AS jsonb), 'editor_export', :target_id, NOW(), NOW()
                )
                """
            ),
            {
                "id": new_id("ntf"),
                "user_id": owner,
                "payload": json.dumps(
                    {
                        "export_id": export.id,
                        "status": export.status,
                        "operation": "drama_export",
                    }
                ),
                "target_id": export.id,
            },
        )

    op.create_index(
        "ix_notifications_user_updated",
        "notifications",
        ["user_id", "updated_at"],
    )
    op.create_index(
        "uq_notifications_user_creation_target",
        "notifications",
        ["user_id", "target_type", "target_id"],
        unique=True,
        postgresql_where=sa.text(
            "target_type IN ('generation_job', 'editor_export') AND target_id IS NOT NULL"
        ),
    )


def downgrade() -> None:
    op.drop_index("uq_notifications_user_creation_target", table_name="notifications")
    op.drop_index("ix_notifications_user_updated", table_name="notifications")
