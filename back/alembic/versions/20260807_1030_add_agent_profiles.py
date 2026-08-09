"""add agent profiles and prompt slots

Revision ID: 7b1c4a5e9d02
Revises: 403d2794785b
Create Date: 2026-08-07 10:30:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "7b1c4a5e9d02"
down_revision: str | None = "403d2794785b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Mirrors `app.domain.agent_skills.service.DEFAULT_NODES` at the time of this
# migration. Inlined rather than imported so a later edit to the seed list
# cannot retroactively change what this migration did.
_SEED_ROLES: tuple[tuple[str, str], ...] = (
    ("safety", "安全审核"),
    ("planner", "任务规划"),
    ("quality", "质量评估"),
    ("copy", "文案生成"),
    ("intent_router", "意图理解路由"),
)


def upgrade() -> None:
    op.create_table(
        "agent_profiles",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("role", sa.String(length=40), nullable=False),
        sa.Column("key", sa.String(length=40), nullable=False),
        sa.Column("display_name", sa.String(length=80), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "operations_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_profiles")),
        sa.UniqueConstraint("role", "key", name="uq_agent_profiles_role_key"),
    )
    op.create_index(
        "ix_agent_profiles_role_enabled", "agent_profiles", ["role", "enabled"], unique=False
    )

    # One default variant per role that already has a node row, plus the
    # built-in roles, so a deployment that never ran `seed` still ends up
    # with somewhere for its existing prompts to hang.
    op.execute(
        sa.text(
            """
            INSERT INTO agent_profiles
                (id, role, key, display_name, description, operations_json,
                 is_default, enabled, created_at)
            SELECT
                'aprof_migrate_' || role,
                role,
                'default',
                COALESCE(display_name, role) || ' · 默认',
                '迁移生成的默认变体：未显式绑定变体的工作流节点都会回落到这里。',
                '[]'::jsonb,
                true,
                true,
                now()
            FROM agent_nodes
            """
        )
    )
    for role, display_name in _SEED_ROLES:
        op.execute(
            sa.text(
                """
                INSERT INTO agent_profiles
                    (id, role, key, display_name, description, operations_json,
                     is_default, enabled, created_at)
                SELECT
                    'aprof_migrate_' || :role, :role, 'default', :display_name,
                    '迁移生成的默认变体：未显式绑定变体的工作流节点都会回落到这里。',
                    '[]'::jsonb, true, true, now()
                WHERE NOT EXISTS (
                    SELECT 1 FROM agent_profiles WHERE role = :role AND key = 'default'
                )
                """
            ).bindparams(role=role, display_name=f"{display_name} · 默认")
        )

    op.add_column("agent_skills", sa.Column("profile_id", sa.String(length=40), nullable=True))
    op.add_column("agent_skills", sa.Column("slot", sa.String(length=40), nullable=True))

    # `intent_router` and `copy` are the two roles whose historical prompt
    # chain is ambiguous: each owns two unrelated system prompts that both
    # ran under the role name, so whichever text an operator last published
    # overwrote both. Existing versions land in each role's primary slot —
    # the one the console actually surfaced — and operators should re-check
    # any published prompt for these two roles after this migration.
    op.execute(
        sa.text(
            """
            UPDATE agent_skills
            SET slot = CASE node_role
                    WHEN 'intent_router' THEN 'classify'
                    WHEN 'copy' THEN 'suggest'
                    ELSE 'default'
                END,
                profile_id = (
                    SELECT p.id FROM agent_profiles p
                    WHERE p.role = agent_skills.node_role AND p.key = 'default'
                )
            """
        )
    )
    # A prompt published for a role that has neither a node nor a seeded
    # default variant would otherwise block the NOT NULL below.
    op.execute(
        sa.text(
            """
            INSERT INTO agent_profiles
                (id, role, key, display_name, description, operations_json,
                 is_default, enabled, created_at)
            SELECT DISTINCT
                'aprof_migrate_' || node_role, node_role, 'default',
                node_role || ' · 默认',
                '迁移生成的默认变体：该角色有历史提示词但没有节点定义。',
                '[]'::jsonb, true, true, now()
            FROM agent_skills WHERE profile_id IS NULL
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE agent_skills
            SET profile_id = (
                SELECT p.id FROM agent_profiles p
                WHERE p.role = agent_skills.node_role AND p.key = 'default'
            )
            WHERE profile_id IS NULL
            """
        )
    )

    op.alter_column("agent_skills", "profile_id", nullable=False)
    op.alter_column("agent_skills", "slot", nullable=False)
    op.create_foreign_key(
        op.f("fk_agent_skills_profile_id_agent_profiles"),
        "agent_skills",
        "agent_profiles",
        ["profile_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_constraint("uq_agent_skills_role_version", "agent_skills", type_="unique")
    op.create_unique_constraint(
        "uq_agent_skills_profile_slot_version", "agent_skills", ["profile_id", "slot", "version"]
    )
    op.create_index(
        "ix_agent_skills_profile_slot_active",
        "agent_skills",
        ["profile_id", "slot", "is_active"],
        unique=False,
    )

    op.add_column("agent_runs", sa.Column("agent_profile_id", sa.String(length=40), nullable=True))
    op.add_column("agent_runs", sa.Column("prompt_slot", sa.String(length=40), nullable=True))


def downgrade() -> None:
    op.drop_column("agent_runs", "prompt_slot")
    op.drop_column("agent_runs", "agent_profile_id")

    op.drop_index("ix_agent_skills_profile_slot_active", table_name="agent_skills")
    op.drop_constraint("uq_agent_skills_profile_slot_version", "agent_skills", type_="unique")
    # Two variants of one role can hold the same version number, so collapsing
    # back to the role-scoped unique constraint needs the duplicates gone.
    # Keeping the default variant's chain matches what upgrade() migrated in.
    op.execute(
        sa.text(
            """
            DELETE FROM agent_skills
            WHERE profile_id NOT IN (SELECT id FROM agent_profiles WHERE key = 'default')
               OR slot IN ('select_provider', 'enhance')
            """
        )
    )
    op.create_unique_constraint(
        "uq_agent_skills_role_version", "agent_skills", ["node_role", "version"]
    )
    op.drop_constraint(
        op.f("fk_agent_skills_profile_id_agent_profiles"), "agent_skills", type_="foreignkey"
    )
    op.drop_column("agent_skills", "slot")
    op.drop_column("agent_skills", "profile_id")

    op.drop_index("ix_agent_profiles_role_enabled", table_name="agent_profiles")
    op.drop_table("agent_profiles")
