"""add episode script turn thinking text

Relationship-adjacent trace column, not backfilled: existing turns simply
read back the empty-string default (see `EpisodeScriptTurn.thinking_text`'s
docstring in `app.models.editor`).

Revision ID: 865f5af713b7
Revises: 582b6e10168d
Create Date: 2026-08-28 10:56:57.432890+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '865f5af713b7'
down_revision: str | None = '582b6e10168d'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'episode_script_turns',
        sa.Column('thinking_text', sa.Text(), server_default='', nullable=False),
    )


def downgrade() -> None:
    op.drop_column('episode_script_turns', 'thinking_text')
