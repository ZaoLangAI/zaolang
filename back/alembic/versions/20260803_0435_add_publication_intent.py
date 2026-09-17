"""add publication intent

Revision ID: 842f9d1d6c19
Revises: e578a7e54fd3
Create Date: 2026-08-03 04:35:41.725760+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '842f9d1d6c19'
down_revision: str | None = 'e578a7e54fd3'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # `channel` and `status` are written by the ORM on every insert, so they
    # need no server_default: the table starts empty.
    op.create_table('publication_intents',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('work_id', sa.String(length=40), nullable=False),
    sa.Column('user_id', sa.String(length=40), nullable=False),
    sa.Column('channel', sa.String(length=32), nullable=False),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('payload_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('external_post_id', sa.String(length=128), nullable=True),
    sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_publication_intents_user_id_users'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['work_id'], ['works.id'], name=op.f('fk_publication_intents_work_id_works'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_publication_intents'))
    )
    op.create_index('ix_publication_intents_user_id_channel', 'publication_intents', ['user_id', 'channel'], unique=False)
    op.create_index('ix_publication_intents_work_id', 'publication_intents', ['work_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_publication_intents_work_id', table_name='publication_intents')
    op.drop_index('ix_publication_intents_user_id_channel', table_name='publication_intents')
    op.drop_table('publication_intents')
