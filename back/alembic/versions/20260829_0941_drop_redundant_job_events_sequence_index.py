"""drop redundant job events sequence index

Revision ID: dd368efe1016
Revises: 2bdefd8d370f
Create Date: 2026-08-29 09:41:12.745014+00:00

`uq_job_events_job_sequence` (a unique constraint on the same two columns,
same order) already gives Postgres a `(job_id, sequence)` B-tree. This index
served no query the constraint's own index could not, and only cost every
insert an extra write.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "dd368efe1016"
down_revision: str | None = "2bdefd8d370f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("ix_job_events_job_id_sequence", table_name="job_events")


def downgrade() -> None:
    op.create_index("ix_job_events_job_id_sequence", "job_events", ["job_id", "sequence"])
