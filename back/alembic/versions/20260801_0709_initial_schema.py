"""initial schema

Revision ID: e578a7e54fd3
Revises: 
Create Date: 2026-08-01 07:09:46.328512+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = 'e578a7e54fd3'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Self-contained so `alembic upgrade head` works against a bare database,
    # such as a CI service container that never ran the init scripts.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.create_table('credit_packages',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('slug', sa.String(length=64), nullable=False),
    sa.Column('credits', sa.Integer(), nullable=False),
    sa.Column('bonus_credits', sa.Integer(), nullable=False),
    sa.Column('price_minor', sa.Integer(), nullable=False),
    sa.Column('currency', sa.String(length=8), nullable=False),
    sa.Column('region', sa.String(length=16), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('sort_order', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_credit_packages')),
    sa.UniqueConstraint('slug', name=op.f('uq_credit_packages_slug'))
    )
    op.create_table('provider_stats',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('provider', sa.String(length=64), nullable=False),
    sa.Column('operation', sa.String(length=32), nullable=False),
    sa.Column('quality_tier', sa.String(length=24), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('successes', sa.Integer(), nullable=False),
    sa.Column('total_latency_ms', sa.BigInteger(), nullable=False),
    sa.Column('total_cost_minor', sa.BigInteger(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_provider_stats')),
    sa.UniqueConstraint('provider', 'operation', 'quality_tier', name='uq_provider_stats_dimension')
    )
    op.create_table('reconciliation_reports',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('generated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('account_count', sa.Integer(), nullable=False),
    sa.Column('mismatched_account_count', sa.Integer(), nullable=False),
    sa.Column('dangling_reserved_count', sa.Integer(), nullable=False),
    sa.Column('details_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_reconciliation_reports'))
    )
    op.create_table('tags',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('slug', sa.String(length=64), nullable=False),
    sa.Column('label_zh', sa.String(length=64), nullable=False),
    sa.Column('label_en', sa.String(length=64), nullable=False),
    sa.Column('label_ja', sa.String(length=64), nullable=False),
    sa.Column('usage_count', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_tags')),
    sa.UniqueConstraint('slug', name=op.f('uq_tags_slug'))
    )
    op.create_table('users',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('email', sa.String(length=320), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('identity_provider_id', sa.String(length=255), nullable=True),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('age_gate_confirmed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('region', sa.String(length=16), nullable=False),
    sa.Column('locale', sa.String(length=16), nullable=False),
    sa.Column('theme', sa.String(length=16), nullable=False),
    sa.Column('roles', sa.ARRAY(sa.String(length=32)), nullable=False),
    sa.Column('suspended_reason', sa.Text(), nullable=True),
    sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_users')),
    sa.UniqueConstraint('email', name=op.f('uq_users_email'))
    )
    op.create_index('ix_users_status', 'users', ['status'], unique=False)
    op.create_table('webhook_events',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('provider', sa.String(length=32), nullable=False),
    sa.Column('external_event_id', sa.String(length=160), nullable=False),
    sa.Column('event_type', sa.String(length=64), nullable=False),
    sa.Column('payload_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_webhook_events')),
    sa.UniqueConstraint('provider', 'external_event_id', name='uq_webhook_events_external')
    )
    op.create_table('workflows',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('slug', sa.String(length=64), nullable=False),
    sa.Column('operation', sa.String(length=32), nullable=False),
    sa.Column('provider_kind', sa.String(length=32), nullable=False),
    sa.Column('display_name', sa.String(length=120), nullable=False),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_workflows')),
    sa.UniqueConstraint('slug', name=op.f('uq_workflows_slug'))
    )
    op.create_table('announcements',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('kind', sa.String(length=24), nullable=False),
    sa.Column('title_zh', sa.String(length=200), nullable=False),
    sa.Column('title_en', sa.String(length=200), nullable=False),
    sa.Column('body_zh', sa.Text(), nullable=False),
    sa.Column('body_en', sa.Text(), nullable=False),
    sa.Column('starts_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('ends_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('is_published', sa.Boolean(), nullable=False),
    sa.Column('created_by_user_id', sa.String(length=40), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], name=op.f('fk_announcements_created_by_user_id_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_announcements'))
    )
    op.create_table('assets',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('owner_user_id', sa.String(length=40), nullable=False),
    sa.Column('object_key', sa.String(length=512), nullable=False),
    sa.Column('media_type', sa.String(length=16), nullable=False),
    sa.Column('mime_type', sa.String(length=128), nullable=False),
    sa.Column('size_bytes', sa.BigInteger(), nullable=False),
    sa.Column('checksum_sha256', sa.String(length=64), nullable=False),
    sa.Column('role', sa.String(length=32), nullable=False),
    sa.Column('width', sa.Integer(), nullable=True),
    sa.Column('height', sa.Integer(), nullable=True),
    sa.Column('duration_ms', sa.Integer(), nullable=True),
    sa.Column('moderation_status', sa.String(length=24), nullable=False),
    sa.Column('visibility', sa.String(length=24), nullable=False),
    sa.Column('is_prototype', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['owner_user_id'], ['users.id'], name=op.f('fk_assets_owner_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_assets')),
    sa.UniqueConstraint('object_key', name=op.f('uq_assets_object_key'))
    )
    op.create_index('ix_assets_checksum_sha256', 'assets', ['checksum_sha256'], unique=False)
    op.create_index('ix_assets_owner_user_id_role', 'assets', ['owner_user_id', 'role'], unique=False)
    op.create_table('audit_logs',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('actor_user_id', sa.String(length=40), nullable=True),
    sa.Column('actor_roles', sa.String(length=160), nullable=True),
    sa.Column('action', sa.String(length=64), nullable=False),
    sa.Column('target_type', sa.String(length=32), nullable=False),
    sa.Column('target_id', sa.String(length=40), nullable=True),
    sa.Column('before_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('after_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('request_id', sa.String(length=64), nullable=True),
    sa.Column('ip_address', sa.String(length=64), nullable=True),
    sa.Column('user_agent', sa.String(length=255), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['actor_user_id'], ['users.id'], name=op.f('fk_audit_logs_actor_user_id_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_audit_logs'))
    )
    op.create_index('ix_audit_logs_action', 'audit_logs', ['action'], unique=False)
    op.create_index('ix_audit_logs_actor', 'audit_logs', ['actor_user_id'], unique=False)
    op.create_index('ix_audit_logs_created_at', 'audit_logs', ['created_at'], unique=False)
    op.create_index('ix_audit_logs_target', 'audit_logs', ['target_type', 'target_id'], unique=False)
    op.create_table('backup_records',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('kind', sa.String(length=24), nullable=False),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('object_key', sa.String(length=512), nullable=True),
    sa.Column('size_bytes', sa.Integer(), nullable=True),
    sa.Column('message', sa.Text(), nullable=True),
    sa.Column('triggered_by_user_id', sa.String(length=40), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['triggered_by_user_id'], ['users.id'], name=op.f('fk_backup_records_triggered_by_user_id_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_backup_records'))
    )
    op.create_table('collections',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('owner_user_id', sa.String(length=40), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('is_public', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['owner_user_id'], ['users.id'], name=op.f('fk_collections_owner_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_collections'))
    )
    op.create_table('credit_accounts',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('user_id', sa.String(length=40), nullable=False),
    sa.Column('currency', sa.String(length=16), nullable=False),
    sa.Column('available_balance', sa.BigInteger(), nullable=False),
    sa.Column('reserved_balance', sa.BigInteger(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('available_balance >= 0', name=op.f('ck_credit_accounts_available_balance_non_negative')),
    sa.CheckConstraint('reserved_balance >= 0', name=op.f('ck_credit_accounts_reserved_balance_non_negative')),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_credit_accounts_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_credit_accounts')),
    sa.UniqueConstraint('user_id', name=op.f('uq_credit_accounts_user_id'))
    )
    op.create_table('data_requests',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('user_id', sa.String(length=40), nullable=False),
    sa.Column('type', sa.String(length=24), nullable=False),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('result_object_key', sa.String(length=512), nullable=True),
    sa.Column('handled_by_user_id', sa.String(length=40), nullable=True),
    sa.Column('handled_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['handled_by_user_id'], ['users.id'], name=op.f('fk_data_requests_handled_by_user_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_data_requests_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_data_requests'))
    )
    op.create_index('ix_data_requests_status', 'data_requests', ['status'], unique=False)
    op.create_table('follows',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('follower_user_id', sa.String(length=40), nullable=False),
    sa.Column('followed_user_id', sa.String(length=40), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['followed_user_id'], ['users.id'], name=op.f('fk_follows_followed_user_id_users'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['follower_user_id'], ['users.id'], name=op.f('fk_follows_follower_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_follows')),
    sa.UniqueConstraint('follower_user_id', 'followed_user_id', name='uq_follows_pair')
    )
    op.create_index('ix_follows_followed_user_id', 'follows', ['followed_user_id'], unique=False)
    op.create_table('idempotency_records',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('user_id', sa.String(length=40), nullable=False),
    sa.Column('endpoint', sa.String(length=120), nullable=False),
    sa.Column('idempotency_key', sa.String(length=160), nullable=False),
    sa.Column('request_hash', sa.String(length=64), nullable=False),
    sa.Column('response_status', sa.Integer(), nullable=False),
    sa.Column('response_snapshot', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_idempotency_records_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_idempotency_records')),
    sa.UniqueConstraint('user_id', 'endpoint', 'idempotency_key', name='uq_idempotency_user_endpoint_key')
    )
    op.create_table('moderation_queue_items',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('subject_type', sa.String(length=32), nullable=False),
    sa.Column('subject_id', sa.String(length=40), nullable=False),
    sa.Column('stage', sa.String(length=32), nullable=False),
    sa.Column('priority', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('reason_code', sa.String(length=64), nullable=True),
    sa.Column('claimed_by_user_id', sa.String(length=40), nullable=True),
    sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['claimed_by_user_id'], ['users.id'], name=op.f('fk_moderation_queue_items_claimed_by_user_id_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_moderation_queue_items')),
    sa.UniqueConstraint('subject_type', 'subject_id', 'stage', name='uq_moderation_queue_subject')
    )
    op.create_index('ix_moderation_queue_status_priority', 'moderation_queue_items', ['status', 'priority'], unique=False)
    op.create_table('moderation_results',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('stage', sa.String(length=32), nullable=False),
    sa.Column('subject_type', sa.String(length=32), nullable=False),
    sa.Column('subject_id', sa.String(length=40), nullable=False),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('categories_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('reason_code', sa.String(length=64), nullable=True),
    sa.Column('public_message', sa.Text(), nullable=True),
    sa.Column('decided_by', sa.String(length=32), nullable=False),
    sa.Column('reviewer_user_id', sa.String(length=40), nullable=True),
    sa.Column('agent_run_id', sa.String(length=40), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['reviewer_user_id'], ['users.id'], name=op.f('fk_moderation_results_reviewer_user_id_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_moderation_results'))
    )
    op.create_index('ix_moderation_results_status_created', 'moderation_results', ['status', 'created_at'], unique=False)
    op.create_index('ix_moderation_results_subject', 'moderation_results', ['subject_type', 'subject_id'], unique=False)
    op.create_table('notifications',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('user_id', sa.String(length=40), nullable=False),
    sa.Column('type', sa.String(length=32), nullable=False),
    sa.Column('title_key', sa.String(length=80), nullable=False),
    sa.Column('payload_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('target_type', sa.String(length=32), nullable=True),
    sa.Column('target_id', sa.String(length=40), nullable=True),
    sa.Column('read_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_notifications_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_notifications'))
    )
    op.create_index('ix_notifications_user_created', 'notifications', ['user_id', 'created_at'], unique=False)
    op.create_table('payment_intents',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('user_id', sa.String(length=40), nullable=False),
    sa.Column('package_id', sa.String(length=40), nullable=False),
    sa.Column('provider', sa.String(length=32), nullable=False),
    sa.Column('external_reference', sa.String(length=160), nullable=False),
    sa.Column('amount_minor', sa.Integer(), nullable=False),
    sa.Column('currency', sa.String(length=8), nullable=False),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('idempotency_key', sa.String(length=160), nullable=False),
    sa.Column('settled_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['package_id'], ['credit_packages.id'], name=op.f('fk_payment_intents_package_id_credit_packages'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_payment_intents_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_payment_intents')),
    sa.UniqueConstraint('external_reference', name=op.f('uq_payment_intents_external_reference')),
    sa.UniqueConstraint('user_id', 'idempotency_key', name='uq_payment_intents_idempotency')
    )
    op.create_table('platform_configs',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('key', sa.String(length=64), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('value_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('created_by_user_id', sa.String(length=40), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], name=op.f('fk_platform_configs_created_by_user_id_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_platform_configs')),
    sa.UniqueConstraint('key', 'version', name='uq_platform_configs_key_version')
    )
    op.create_index('ix_platform_configs_key_active', 'platform_configs', ['key', 'is_active'], unique=False)
    op.create_table('report_cases',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('reporter_user_id', sa.String(length=40), nullable=True),
    sa.Column('subject_type', sa.String(length=32), nullable=False),
    sa.Column('subject_id', sa.String(length=40), nullable=False),
    sa.Column('reason', sa.String(length=32), nullable=False),
    sa.Column('detail', sa.Text(), nullable=True),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('resolution_note', sa.Text(), nullable=True),
    sa.Column('handled_by_user_id', sa.String(length=40), nullable=True),
    sa.Column('handled_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['handled_by_user_id'], ['users.id'], name=op.f('fk_report_cases_handled_by_user_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['reporter_user_id'], ['users.id'], name=op.f('fk_report_cases_reporter_user_id_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_report_cases'))
    )
    op.create_index('ix_report_cases_status_created', 'report_cases', ['status', 'created_at'], unique=False)
    op.create_index('ix_report_cases_subject', 'report_cases', ['subject_type', 'subject_id'], unique=False)
    op.create_table('workflow_versions',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('workflow_id', sa.String(length=40), nullable=False),
    sa.Column('semantic_version', sa.String(length=32), nullable=False),
    sa.Column('capability_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('parameter_schema_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('locked_definition_hash', sa.String(length=64), nullable=False),
    sa.Column('is_approved', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['workflow_id'], ['workflows.id'], name=op.f('fk_workflow_versions_workflow_id_workflows'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_workflow_versions')),
    sa.UniqueConstraint('workflow_id', 'semantic_version', name='uq_workflow_versions_semver')
    )
    op.create_table('works',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('owner_user_id', sa.String(length=40), nullable=False),
    sa.Column('current_version_id', sa.String(length=40), nullable=True),
    sa.Column('visibility', sa.String(length=24), nullable=False),
    sa.Column('lifecycle_status', sa.String(length=24), nullable=False),
    sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('tombstoned_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('tombstone_reason', sa.Text(), nullable=True),
    sa.Column('view_count', sa.BigInteger(), nullable=False),
    sa.Column('like_count', sa.BigInteger(), nullable=False),
    sa.Column('comment_count', sa.BigInteger(), nullable=False),
    sa.Column('remix_count', sa.BigInteger(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['owner_user_id'], ['users.id'], name=op.f('fk_works_owner_user_id_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_works'))
    )
    op.create_index('ix_works_owner_user_id', 'works', ['owner_user_id'], unique=False)
    op.create_index('ix_works_published_at', 'works', ['published_at'], unique=False)
    op.create_index('ix_works_visibility_lifecycle_status', 'works', ['visibility', 'lifecycle_status'], unique=False)
    op.create_table('asset_consents',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('asset_id', sa.String(length=40), nullable=False),
    sa.Column('consent_type', sa.String(length=32), nullable=False),
    sa.Column('subject_reference', sa.String(length=255), nullable=False),
    sa.Column('evidence_asset_id', sa.String(length=40), nullable=True),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['asset_id'], ['assets.id'], name=op.f('fk_asset_consents_asset_id_assets'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['evidence_asset_id'], ['assets.id'], name=op.f('fk_asset_consents_evidence_asset_id_assets'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_asset_consents'))
    )
    op.create_index('ix_asset_consents_asset_id', 'asset_consents', ['asset_id'], unique=False)
    op.create_table('bookmarks',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('user_id', sa.String(length=40), nullable=False),
    sa.Column('work_id', sa.String(length=40), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_bookmarks_user_id_users'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['work_id'], ['works.id'], name=op.f('fk_bookmarks_work_id_works'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_bookmarks')),
    sa.UniqueConstraint('user_id', 'work_id', name='uq_bookmarks_user_work')
    )
    op.create_table('collection_items',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('collection_id', sa.String(length=40), nullable=False),
    sa.Column('work_id', sa.String(length=40), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['collection_id'], ['collections.id'], name=op.f('fk_collection_items_collection_id_collections'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['work_id'], ['works.id'], name=op.f('fk_collection_items_work_id_works'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_collection_items')),
    sa.UniqueConstraint('collection_id', 'work_id', name='uq_collection_items_pair')
    )
    op.create_table('content_fingerprints',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('asset_id', sa.String(length=40), nullable=False),
    sa.Column('algorithm', sa.String(length=24), nullable=False),
    sa.Column('fingerprint_hex', sa.String(length=64), nullable=False),
    sa.Column('fingerprint_bits', sa.BigInteger(), nullable=False),
    sa.Column('frame_index', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['asset_id'], ['assets.id'], name=op.f('fk_content_fingerprints_asset_id_assets'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_content_fingerprints')),
    sa.UniqueConstraint('asset_id', 'algorithm', 'frame_index', name='uq_fingerprint_asset_frame')
    )
    op.create_index('ix_content_fingerprints_fingerprint_bits', 'content_fingerprints', ['fingerprint_bits'], unique=False)
    op.create_table('likes',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('user_id', sa.String(length=40), nullable=False),
    sa.Column('work_id', sa.String(length=40), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_likes_user_id_users'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['work_id'], ['works.id'], name=op.f('fk_likes_work_id_works'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_likes')),
    sa.UniqueConstraint('user_id', 'work_id', name='uq_likes_user_work')
    )
    op.create_table('profiles',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('user_id', sa.String(length=40), nullable=False),
    sa.Column('display_name', sa.String(length=80), nullable=False),
    sa.Column('handle', sa.String(length=40), nullable=False),
    sa.Column('bio', sa.Text(), nullable=True),
    sa.Column('location', sa.String(length=80), nullable=True),
    sa.Column('avatar_asset_id', sa.String(length=40), nullable=True),
    sa.Column('cover_asset_id', sa.String(length=40), nullable=True),
    sa.Column('public_profile', sa.Boolean(), nullable=False),
    sa.Column('notify_on_remix', sa.Boolean(), nullable=False),
    sa.Column('reduce_motion', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['avatar_asset_id'], ['assets.id'], name=op.f('fk_profiles_avatar_asset_id_assets'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['cover_asset_id'], ['assets.id'], name=op.f('fk_profiles_cover_asset_id_assets'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_profiles_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_profiles')),
    sa.UniqueConstraint('handle', name=op.f('uq_profiles_handle')),
    sa.UniqueConstraint('user_id', name=op.f('uq_profiles_user_id'))
    )
    op.create_table('provenance_manifests',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('asset_id', sa.String(length=40), nullable=False),
    sa.Column('generation_job_id', sa.String(length=40), nullable=True),
    sa.Column('claim_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('signature', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['asset_id'], ['assets.id'], name=op.f('fk_provenance_manifests_asset_id_assets'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_provenance_manifests')),
    sa.UniqueConstraint('asset_id', name=op.f('uq_provenance_manifests_asset_id'))
    )
    op.create_table('upload_sessions',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('user_id', sa.String(length=40), nullable=False),
    sa.Column('object_key', sa.String(length=512), nullable=False),
    sa.Column('purpose', sa.String(length=32), nullable=False),
    sa.Column('mime_type', sa.String(length=128), nullable=False),
    sa.Column('declared_size_bytes', sa.BigInteger(), nullable=False),
    sa.Column('declared_checksum_sha256', sa.String(length=64), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('asset_id', sa.String(length=40), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['asset_id'], ['assets.id'], name=op.f('fk_upload_sessions_asset_id_assets'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_upload_sessions_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_upload_sessions')),
    sa.UniqueConstraint('object_key', name=op.f('uq_upload_sessions_object_key'))
    )
    op.create_index('ix_upload_sessions_user_id', 'upload_sessions', ['user_id'], unique=False)
    op.create_table('work_tags',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('work_id', sa.String(length=40), nullable=False),
    sa.Column('tag_id', sa.String(length=40), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['tag_id'], ['tags.id'], name=op.f('fk_work_tags_tag_id_tags'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['work_id'], ['works.id'], name=op.f('fk_work_tags_work_id_works'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_work_tags')),
    sa.UniqueConstraint('work_id', 'tag_id', name='uq_work_tags_pair')
    )
    op.create_table('work_versions',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('work_id', sa.String(length=40), nullable=False),
    sa.Column('version_number', sa.Integer(), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('cover_asset_id', sa.String(length=40), nullable=True),
    sa.Column('primary_output_asset_id', sa.String(length=40), nullable=True),
    sa.Column('ai_generated', sa.Boolean(), nullable=False),
    sa.Column('workflow_version_id', sa.String(length=40), nullable=True),
    sa.Column('generation_job_id', sa.String(length=40), nullable=True),
    sa.Column('license_snapshot_id', sa.String(length=40), nullable=True),
    sa.Column('reusable_params_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('immutable_created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['cover_asset_id'], ['assets.id'], name=op.f('fk_work_versions_cover_asset_id_assets'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['primary_output_asset_id'], ['assets.id'], name=op.f('fk_work_versions_primary_output_asset_id_assets'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['work_id'], ['works.id'], name=op.f('fk_work_versions_work_id_works'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['workflow_version_id'], ['workflow_versions.id'], name=op.f('fk_work_versions_workflow_version_id_workflow_versions'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_work_versions')),
    sa.UniqueConstraint('work_id', 'version_number', name='uq_work_versions_work_version')
    )
    op.create_index('ix_work_versions_work_id', 'work_versions', ['work_id'], unique=False)
    op.create_table('license_snapshots',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('license_type', sa.String(length=32), nullable=False),
    sa.Column('permissions_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('attribution_text', sa.Text(), nullable=False),
    sa.Column('source_work_version_id', sa.String(length=40), nullable=False),
    sa.Column('captured_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['source_work_version_id'], ['work_versions.id'], name=op.f('fk_license_snapshots_source_work_version_id_work_versions'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_license_snapshots'))
    )
    op.create_index('ix_license_snapshots_source', 'license_snapshots', ['source_work_version_id'], unique=False)
    op.create_table('style_presets',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('owner_user_id', sa.String(length=40), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('params_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('derived_from_work_version_id', sa.String(length=40), nullable=True),
    sa.Column('is_public', sa.Boolean(), nullable=False),
    sa.Column('apply_count', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['derived_from_work_version_id'], ['work_versions.id'], name=op.f('fk_style_presets_derived_from_work_version_id_work_versions'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['owner_user_id'], ['users.id'], name=op.f('fk_style_presets_owner_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_style_presets'))
    )
    op.create_index('ix_style_presets_owner', 'style_presets', ['owner_user_id'], unique=False)
    op.create_table('work_embeddings',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('work_id', sa.String(length=40), nullable=False),
    sa.Column('work_version_id', sa.String(length=40), nullable=False),
    sa.Column('provider', sa.String(length=32), nullable=False),
    sa.Column('embedding', pgvector.sqlalchemy.vector.VECTOR(dim=256), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['work_id'], ['works.id'], name=op.f('fk_work_embeddings_work_id_works'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['work_version_id'], ['work_versions.id'], name=op.f('fk_work_embeddings_work_version_id_work_versions'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_work_embeddings')),
    sa.UniqueConstraint('work_version_id', 'provider', name='uq_work_embeddings_version_provider')
    )
    op.create_index('ix_work_embeddings_vector', 'work_embeddings', ['embedding'], unique=False, postgresql_using='hnsw', postgresql_with={'m': 16, 'ef_construction': 64}, postgresql_ops={'embedding': 'vector_cosine_ops'})
    op.create_table('drafts',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('user_id', sa.String(length=40), nullable=False),
    sa.Column('source_work_version_id', sa.String(length=40), nullable=True),
    sa.Column('license_snapshot_id', sa.String(length=40), nullable=True),
    sa.Column('title', sa.String(length=200), nullable=True),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('params_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('latest_job_id', sa.String(length=40), nullable=True),
    sa.Column('output_asset_id', sa.String(length=40), nullable=True),
    sa.Column('published_work_id', sa.String(length=40), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['license_snapshot_id'], ['license_snapshots.id'], name=op.f('fk_drafts_license_snapshot_id_license_snapshots'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['output_asset_id'], ['assets.id'], name=op.f('fk_drafts_output_asset_id_assets'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['published_work_id'], ['works.id'], name=op.f('fk_drafts_published_work_id_works'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['source_work_version_id'], ['work_versions.id'], name=op.f('fk_drafts_source_work_version_id_work_versions'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_drafts_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_drafts'))
    )
    op.create_index('ix_drafts_user_id', 'drafts', ['user_id'], unique=False)
    op.create_table('lineage_edges',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('parent_work_version_id', sa.String(length=40), nullable=False),
    sa.Column('child_work_version_id', sa.String(length=40), nullable=False),
    sa.Column('parent_author_snapshot_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('license_snapshot_id', sa.String(length=40), nullable=False),
    sa.Column('workflow_version_id', sa.String(length=40), nullable=True),
    sa.Column('reused_asset_ids_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('depth', sa.Integer(), nullable=False),
    sa.Column('created_by_user_id', sa.String(length=40), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['child_work_version_id'], ['work_versions.id'], name=op.f('fk_lineage_edges_child_work_version_id_work_versions'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], name=op.f('fk_lineage_edges_created_by_user_id_users'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['license_snapshot_id'], ['license_snapshots.id'], name=op.f('fk_lineage_edges_license_snapshot_id_license_snapshots'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['parent_work_version_id'], ['work_versions.id'], name=op.f('fk_lineage_edges_parent_work_version_id_work_versions'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['workflow_version_id'], ['workflow_versions.id'], name=op.f('fk_lineage_edges_workflow_version_id_workflow_versions'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_lineage_edges')),
    sa.UniqueConstraint('child_work_version_id', name=op.f('uq_lineage_edges_child_work_version_id'))
    )
    op.create_index('ix_lineage_edges_created_by', 'lineage_edges', ['created_by_user_id'], unique=False)
    op.create_index('ix_lineage_edges_parent', 'lineage_edges', ['parent_work_version_id'], unique=False)
    op.create_table('generation_jobs',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('user_id', sa.String(length=40), nullable=False),
    sa.Column('draft_id', sa.String(length=40), nullable=True),
    sa.Column('source_work_version_id', sa.String(length=40), nullable=True),
    sa.Column('operation', sa.String(length=32), nullable=False),
    sa.Column('request_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('quality_tier', sa.String(length=24), nullable=False),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('quoted_credits', sa.Integer(), nullable=False),
    sa.Column('reserved_credits', sa.Integer(), nullable=False),
    sa.Column('actual_credits', sa.Integer(), nullable=True),
    sa.Column('max_credits', sa.Integer(), nullable=True),
    sa.Column('idempotency_key', sa.String(length=120), nullable=False),
    sa.Column('selected_route_summary_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('routing_trace_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('output_asset_id', sa.String(length=40), nullable=True),
    sa.Column('output_work_version_id', sa.String(length=40), nullable=True),
    sa.Column('estimated_seconds', sa.Integer(), nullable=False),
    sa.Column('failure_code', sa.String(length=64), nullable=True),
    sa.Column('failure_message', sa.Text(), nullable=True),
    sa.Column('cancel_requested_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('retry_of_job_id', sa.String(length=40), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['draft_id'], ['drafts.id'], name=op.f('fk_generation_jobs_draft_id_drafts'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['output_asset_id'], ['assets.id'], name=op.f('fk_generation_jobs_output_asset_id_assets'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['source_work_version_id'], ['work_versions.id'], name=op.f('fk_generation_jobs_source_work_version_id_work_versions'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_generation_jobs_user_id_users'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_generation_jobs')),
    sa.UniqueConstraint('user_id', 'idempotency_key', name='uq_generation_jobs_idempotency')
    )
    op.create_index('ix_generation_jobs_status_created_at', 'generation_jobs', ['status', 'created_at'], unique=False)
    op.create_index('ix_generation_jobs_user_id_status', 'generation_jobs', ['user_id', 'status'], unique=False)
    op.create_table('agent_runs',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('job_id', sa.String(length=40), nullable=True),
    sa.Column('user_id', sa.String(length=40), nullable=True),
    sa.Column('agent_name', sa.String(length=32), nullable=False),
    sa.Column('mode', sa.String(length=32), nullable=False),
    sa.Column('model', sa.String(length=120), nullable=True),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('degraded', sa.Boolean(), nullable=False),
    sa.Column('degrade_reason', sa.String(length=160), nullable=True),
    sa.Column('prompt_tokens', sa.Integer(), nullable=False),
    sa.Column('completion_tokens', sa.Integer(), nullable=False),
    sa.Column('latency_ms', sa.Integer(), nullable=False),
    sa.Column('output_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('request_id', sa.String(length=64), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['job_id'], ['generation_jobs.id'], name=op.f('fk_agent_runs_job_id_generation_jobs'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_agent_runs_user_id_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_agent_runs'))
    )
    op.create_index('ix_agent_runs_agent_name_created_at', 'agent_runs', ['agent_name', 'created_at'], unique=False)
    op.create_index('ix_agent_runs_job_id', 'agent_runs', ['job_id'], unique=False)
    op.create_table('credit_ledger_entries',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('account_id', sa.String(length=40), nullable=False),
    sa.Column('type', sa.String(length=24), nullable=False),
    sa.Column('amount', sa.Integer(), nullable=False),
    sa.Column('balance_after', sa.BigInteger(), nullable=False),
    sa.Column('reserved_after', sa.BigInteger(), nullable=False),
    sa.Column('job_id', sa.String(length=40), nullable=True),
    sa.Column('payment_reference', sa.String(length=160), nullable=True),
    sa.Column('idempotency_key', sa.String(length=160), nullable=True),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('actor_user_id', sa.String(length=40), nullable=True),
    sa.Column('metadata_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['account_id'], ['credit_accounts.id'], name=op.f('fk_credit_ledger_entries_account_id_credit_accounts'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['actor_user_id'], ['users.id'], name=op.f('fk_credit_ledger_entries_actor_user_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['job_id'], ['generation_jobs.id'], name=op.f('fk_credit_ledger_entries_job_id_generation_jobs'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_credit_ledger_entries')),
    sa.UniqueConstraint('idempotency_key', name='uq_credit_ledger_idempotency'),
    sa.UniqueConstraint('job_id', 'type', name='uq_credit_ledger_job_type'),
    sa.UniqueConstraint('payment_reference', name='uq_credit_ledger_payment')
    )
    op.create_index('ix_credit_ledger_account_created', 'credit_ledger_entries', ['account_id', 'created_at'], unique=False)
    op.create_index('ix_credit_ledger_type', 'credit_ledger_entries', ['type'], unique=False)
    op.create_table('job_events',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('job_id', sa.String(length=40), nullable=False),
    sa.Column('sequence', sa.Integer(), nullable=False),
    sa.Column('event_type', sa.String(length=32), nullable=False),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('progress', sa.Integer(), nullable=False),
    sa.Column('public_message', sa.Text(), nullable=False),
    sa.Column('internal_code', sa.String(length=64), nullable=True),
    sa.Column('payload_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['job_id'], ['generation_jobs.id'], name=op.f('fk_job_events_job_id_generation_jobs'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_job_events')),
    sa.UniqueConstraint('job_id', 'sequence', name='uq_job_events_job_sequence')
    )
    op.create_index('ix_job_events_job_id_sequence', 'job_events', ['job_id', 'sequence'], unique=False)
    op.create_table('provider_attempts',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('job_id', sa.String(length=40), nullable=False),
    sa.Column('provider', sa.String(length=64), nullable=False),
    sa.Column('provider_kind', sa.String(length=32), nullable=False),
    sa.Column('model_or_workflow_version', sa.String(length=120), nullable=False),
    sa.Column('external_task_id', sa.String(length=160), nullable=True),
    sa.Column('attempt_number', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('cost_minor', sa.Integer(), nullable=False),
    sa.Column('latency_ms', sa.Integer(), nullable=False),
    sa.Column('failure_code', sa.String(length=64), nullable=True),
    sa.Column('raw_metadata_redacted_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['job_id'], ['generation_jobs.id'], name=op.f('fk_provider_attempts_job_id_generation_jobs'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_provider_attempts')),
    sa.UniqueConstraint('job_id', 'attempt_number', name='uq_provider_attempts_job_attempt')
    )
    op.create_index('ix_provider_attempts_provider_status', 'provider_attempts', ['provider', 'status'], unique=False)
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index('ix_provider_attempts_provider_status', table_name='provider_attempts')
    op.drop_table('provider_attempts')
    op.drop_index('ix_job_events_job_id_sequence', table_name='job_events')
    op.drop_table('job_events')
    op.drop_index('ix_credit_ledger_type', table_name='credit_ledger_entries')
    op.drop_index('ix_credit_ledger_account_created', table_name='credit_ledger_entries')
    op.drop_table('credit_ledger_entries')
    op.drop_index('ix_agent_runs_job_id', table_name='agent_runs')
    op.drop_index('ix_agent_runs_agent_name_created_at', table_name='agent_runs')
    op.drop_table('agent_runs')
    op.drop_index('ix_generation_jobs_user_id_status', table_name='generation_jobs')
    op.drop_index('ix_generation_jobs_status_created_at', table_name='generation_jobs')
    op.drop_table('generation_jobs')
    op.drop_index('ix_lineage_edges_parent', table_name='lineage_edges')
    op.drop_index('ix_lineage_edges_created_by', table_name='lineage_edges')
    op.drop_table('lineage_edges')
    op.drop_index('ix_drafts_user_id', table_name='drafts')
    op.drop_table('drafts')
    op.drop_index('ix_work_embeddings_vector', table_name='work_embeddings', postgresql_using='hnsw', postgresql_with={'m': 16, 'ef_construction': 64}, postgresql_ops={'embedding': 'vector_cosine_ops'})
    op.drop_table('work_embeddings')
    op.drop_index('ix_style_presets_owner', table_name='style_presets')
    op.drop_table('style_presets')
    op.drop_index('ix_license_snapshots_source', table_name='license_snapshots')
    op.drop_table('license_snapshots')
    op.drop_index('ix_work_versions_work_id', table_name='work_versions')
    op.drop_table('work_versions')
    op.drop_table('work_tags')
    op.drop_index('ix_upload_sessions_user_id', table_name='upload_sessions')
    op.drop_table('upload_sessions')
    op.drop_table('provenance_manifests')
    op.drop_table('profiles')
    op.drop_table('likes')
    op.drop_index('ix_content_fingerprints_fingerprint_bits', table_name='content_fingerprints')
    op.drop_table('content_fingerprints')
    op.drop_table('collection_items')
    op.drop_table('bookmarks')
    op.drop_index('ix_asset_consents_asset_id', table_name='asset_consents')
    op.drop_table('asset_consents')
    op.drop_index('ix_works_visibility_lifecycle_status', table_name='works')
    op.drop_index('ix_works_published_at', table_name='works')
    op.drop_index('ix_works_owner_user_id', table_name='works')
    op.drop_table('works')
    op.drop_table('workflow_versions')
    op.drop_index('ix_report_cases_subject', table_name='report_cases')
    op.drop_index('ix_report_cases_status_created', table_name='report_cases')
    op.drop_table('report_cases')
    op.drop_index('ix_platform_configs_key_active', table_name='platform_configs')
    op.drop_table('platform_configs')
    op.drop_table('payment_intents')
    op.drop_index('ix_notifications_user_created', table_name='notifications')
    op.drop_table('notifications')
    op.drop_index('ix_moderation_results_subject', table_name='moderation_results')
    op.drop_index('ix_moderation_results_status_created', table_name='moderation_results')
    op.drop_table('moderation_results')
    op.drop_index('ix_moderation_queue_status_priority', table_name='moderation_queue_items')
    op.drop_table('moderation_queue_items')
    op.drop_table('idempotency_records')
    op.drop_index('ix_follows_followed_user_id', table_name='follows')
    op.drop_table('follows')
    op.drop_index('ix_data_requests_status', table_name='data_requests')
    op.drop_table('data_requests')
    op.drop_table('credit_accounts')
    op.drop_table('collections')
    op.drop_table('backup_records')
    op.drop_index('ix_audit_logs_target', table_name='audit_logs')
    op.drop_index('ix_audit_logs_created_at', table_name='audit_logs')
    op.drop_index('ix_audit_logs_actor', table_name='audit_logs')
    op.drop_index('ix_audit_logs_action', table_name='audit_logs')
    op.drop_table('audit_logs')
    op.drop_index('ix_assets_owner_user_id_role', table_name='assets')
    op.drop_index('ix_assets_checksum_sha256', table_name='assets')
    op.drop_table('assets')
    op.drop_table('announcements')
    op.drop_table('workflows')
    op.drop_table('webhook_events')
    op.drop_index('ix_users_status', table_name='users')
    op.drop_table('users')
    op.drop_table('tags')
    op.drop_table('reconciliation_reports')
    op.drop_table('provider_stats')
    op.drop_table('credit_packages')
    # ### end Alembic commands ###
