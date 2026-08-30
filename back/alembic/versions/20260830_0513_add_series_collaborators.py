"""add series collaborators

Revision ID: 07287ed70a87
Revises: e4c9a1b8d2f0
Create Date: 2026-08-30 05:13:13.709670+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '07287ed70a87'
down_revision: str | None = 'e4c9a1b8d2f0'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'series_collaborators',
        sa.Column('id', sa.String(length=40), nullable=False),
        sa.Column('series_id', sa.String(length=40), nullable=False),
        sa.Column('user_id', sa.String(length=40), nullable=False),
        sa.Column('invited_by_user_id', sa.String(length=40), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('responded_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            'created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False
        ),
        sa.Column(
            'updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ['invited_by_user_id'],
            ['users.id'],
            name=op.f('fk_series_collaborators_invited_by_user_id_users'),
            ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['series_id'],
            ['series.id'],
            name=op.f('fk_series_collaborators_series_id_series'),
            ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['user_id'],
            ['users.id'],
            name=op.f('fk_series_collaborators_user_id_users'),
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_series_collaborators')),
        sa.UniqueConstraint('series_id', 'user_id', name='uq_series_collaborators_series_user'),
    )
    op.create_index(
        'ix_series_collaborators_series_id', 'series_collaborators', ['series_id'], unique=False
    )
    op.create_index(
        'ix_series_collaborators_user_id_status',
        'series_collaborators',
        ['user_id', 'status'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index('ix_series_collaborators_user_id_status', table_name='series_collaborators')
    op.drop_index('ix_series_collaborators_series_id', table_name='series_collaborators')
    op.drop_table('series_collaborators')
