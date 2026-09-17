"""add drama episode source idea

Persists the author's first-draft prompt on `drama_episodes` so an empty
shell (failed or interrupted stream, no `episode_script_turns` yet) can
be retried without asking the user to re-type the idea. Nullable /
default-empty: existing rows stay valid; script writing fills them in
from `prepare_new_script` onward (and `get_script` may backfill a
historical empty shell from a nearby `script_draft` AgentRun).

Revision ID: e4c9a1b8d2f0
Revises: ada14f32676f
Create Date: 2026-08-29 20:22:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "e4c9a1b8d2f0"
down_revision: str | None = "ada14f32676f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("drama_episodes", sa.Column("source_idea", sa.Text(), nullable=True))
    op.add_column(
        "drama_episodes",
        sa.Column(
            "source_referenced_skill_ids_json",
            JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("drama_episodes", "source_referenced_skill_ids_json")
    op.drop_column("drama_episodes", "source_idea")
