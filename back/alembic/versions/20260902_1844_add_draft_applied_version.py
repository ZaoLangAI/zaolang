"""add drafts.applied_job_id and generation_jobs.draft_history_hidden_at

Revision ID: c4d8e1f2a6b0
Revises: 07287ed70a87
Create Date: 2026-09-02 18:44:00.000000+00:00

`applied_job_id` is the draft's currently applied generation (preview /
publish output). Distinct from `latest_job_id`, which still tracks the last
submit so retry notifications reopen that attempt. Backfill prefers the job
whose output matches the draft's current `output_asset_id`, then the
latest succeeded job under the draft.

`draft_history_hidden_at` hides a job from the draft-scoped version strip
without deleting the row (ledger / events / assets must stay).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c4d8e1f2a6b0"
down_revision: str | None = "07287ed70a87"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("drafts", sa.Column("applied_job_id", sa.String(length=40), nullable=True))
    op.add_column(
        "generation_jobs",
        sa.Column("draft_history_hidden_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        sa.text(
            """
            UPDATE drafts AS d
            SET applied_job_id = (
                SELECT j.id
                FROM generation_jobs AS j
                WHERE j.draft_id = d.id
                  AND j.output_asset_id = d.output_asset_id
                  AND j.status = 'succeeded'
                ORDER BY j.created_at DESC
                LIMIT 1
            )
            WHERE d.output_asset_id IS NOT NULL
              AND d.applied_job_id IS NULL
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE drafts AS d
            SET applied_job_id = (
                SELECT j.id
                FROM generation_jobs AS j
                WHERE j.draft_id = d.id
                  AND j.status = 'succeeded'
                  AND j.output_asset_id IS NOT NULL
                ORDER BY j.created_at DESC
                LIMIT 1
            )
            WHERE d.applied_job_id IS NULL
            """
        )
    )


def downgrade() -> None:
    op.drop_column("generation_jobs", "draft_history_hidden_at")
    op.drop_column("drafts", "applied_job_id")
