"""add scenes

A flat, reusable settings library — mirrors `characters` minus the
roster/`series` concept a cast needs and a scene doesn't. See
`app.models.scenes.Scene`.

Revision ID: f3a8c92b7e14
Revises: c4a7f0b2e5d8
Create Date: 2026-08-15 19:00:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = 'f3a8c92b7e14'
down_revision: str | None = 'c4a7f0b2e5d8'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'scenes',
        sa.Column('id', sa.String(length=40), nullable=False),
        sa.Column('owner_user_id', sa.String(length=40), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column(
            'reference_asset_ids_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column(
            'created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False
        ),
        sa.Column(
            'updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ['owner_user_id'],
            ['users.id'],
            name=op.f('fk_scenes_owner_user_id_users'),
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_scenes')),
    )
    op.create_index('ix_scenes_owner_user_id', 'scenes', ['owner_user_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_scenes_owner_user_id', table_name='scenes')
    op.drop_table('scenes')
