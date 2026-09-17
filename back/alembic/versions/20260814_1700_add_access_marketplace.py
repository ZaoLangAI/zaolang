"""add access marketplace grants and prices

Revision ID: f7c5e1a4b9d3
Revises: e6b4d0f3a8c2
Create Date: 2026-08-14 17:00:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f7c5e1a4b9d3"
down_revision: str | None = "e6b4d0f3a8c2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "works",
        sa.Column("access_credits", sa.Integer(), server_default="0", nullable=False),
    )
    op.create_check_constraint(
        "ck_works_access_credits_non_negative", "works", "access_credits >= 0"
    )

    op.add_column(
        "creation_skills",
        sa.Column("access_credits", sa.Integer(), server_default="0", nullable=False),
    )
    op.create_check_constraint(
        "ck_creation_skills_access_credits_non_negative",
        "creation_skills",
        "access_credits >= 0",
    )

    op.add_column("license_snapshots", sa.Column("access_credits", sa.Integer(), nullable=True))
    op.add_column(
        "license_snapshots", sa.Column("access_grant_id", sa.String(length=40), nullable=True)
    )

    op.create_table(
        "access_grants",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("buyer_user_id", sa.String(length=40), nullable=False),
        sa.Column("seller_user_id", sa.String(length=40), nullable=False),
        sa.Column("subject_type", sa.String(length=16), nullable=False),
        sa.Column("subject_id", sa.String(length=40), nullable=False),
        sa.Column("price_credits", sa.Integer(), nullable=False),
        sa.Column("platform_fee_credits", sa.Integer(), nullable=False),
        sa.Column("seller_net_credits", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["buyer_user_id"],
            ["users.id"],
            name=op.f("fk_access_grants_buyer_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["seller_user_id"],
            ["users.id"],
            name=op.f("fk_access_grants_seller_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_access_grants")),
        sa.UniqueConstraint(
            "buyer_user_id",
            "subject_type",
            "subject_id",
            name="uq_access_grants_buyer_subject",
        ),
    )
    op.create_index("ix_access_grants_seller", "access_grants", ["seller_user_id"])
    op.create_index("ix_access_grants_subject", "access_grants", ["subject_type", "subject_id"])


def downgrade() -> None:
    op.drop_index("ix_access_grants_subject", table_name="access_grants")
    op.drop_index("ix_access_grants_seller", table_name="access_grants")
    op.drop_table("access_grants")
    op.drop_column("license_snapshots", "access_grant_id")
    op.drop_column("license_snapshots", "access_credits")
    op.drop_constraint("ck_creation_skills_access_credits_non_negative", "creation_skills")
    op.drop_column("creation_skills", "access_credits")
    op.drop_constraint("ck_works_access_credits_non_negative", "works")
    op.drop_column("works", "access_credits")
