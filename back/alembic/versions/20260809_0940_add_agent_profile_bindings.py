"""add per-variant model bindings and media candidates

Revision ID: 2d0e63bc84a5
Revises: 1c9f2ad4b731
Create Date: 2026-08-09 09:40:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "2d0e63bc84a5"
down_revision: str | None = "1c9f2ad4b731"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # All nullable: an existing variant pins nothing and keeps drawing from
    # the shared `kind="general"` pool exactly as before.
    op.add_column(
        "agent_profiles", sa.Column("default_endpoint_id", sa.String(length=64), nullable=True)
    )
    op.add_column(
        "agent_profiles", sa.Column("backup_endpoint_id", sa.String(length=64), nullable=True)
    )
    op.add_column("agent_profiles", sa.Column("max_tokens", sa.Integer(), nullable=True))
    op.add_column("agent_profiles", sa.Column("temperature_milli", sa.Integer(), nullable=True))
    op.add_column("agent_profiles", sa.Column("reasoning_model", sa.Boolean(), nullable=True))
    op.add_column(
        "agent_profiles",
        sa.Column(
            "media_candidates_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    # Backfill only; the model supplies the default for new rows.
    op.alter_column("agent_profiles", "media_candidates_json", server_default=None)
    op.create_check_constraint(
        "temperature_milli_range",
        "agent_profiles",
        "temperature_milli IS NULL OR (temperature_milli >= 0 AND temperature_milli <= 2000)",
    )
    op.create_check_constraint(
        "backup_requires_default",
        "agent_profiles",
        "backup_endpoint_id IS NULL OR default_endpoint_id IS NOT NULL",
    )


def downgrade() -> None:
    # The bare name, not the rendered one: `ck_%(table_name)s_%(constraint_name)s`
    # from `NAMING_CONVENTION` is applied here too, so passing the full name
    # would look for `ck_agent_profiles_ck_agent_profiles_...`.
    op.drop_constraint("backup_requires_default", "agent_profiles", type_="check")
    op.drop_constraint("temperature_milli_range", "agent_profiles", type_="check")
    op.drop_column("agent_profiles", "media_candidates_json")
    op.drop_column("agent_profiles", "reasoning_model")
    op.drop_column("agent_profiles", "temperature_milli")
    op.drop_column("agent_profiles", "max_tokens")
    op.drop_column("agent_profiles", "backup_endpoint_id")
    op.drop_column("agent_profiles", "default_endpoint_id")
