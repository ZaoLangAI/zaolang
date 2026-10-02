"""add a user-set monthly spend cap to credit accounts

Revision ID: a7c2e9f4b1d6
Revises: f6b1d4a8c3e5
Create Date: 2026-09-14 15:00:00.000000+00:00

`credits.service._apply` enforces the cap inside the same conditional
UPDATE as the balance: `period_spent` is what was reserved for generation in
`spend_period` ("YYYY-MM", UTC), net of what that month released or
returned. `monthly_spend_limit` null means no cap — every existing account.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a7c2e9f4b1d6"
down_revision: str | None = "f6b1d4a8c3e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("credit_accounts", sa.Column("monthly_spend_limit", sa.Integer(), nullable=True))
    op.add_column("credit_accounts", sa.Column("spend_period", sa.String(length=7), nullable=True))
    op.add_column(
        "credit_accounts",
        sa.Column("period_spent", sa.BigInteger(), server_default="0", nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_credit_accounts_period_spent_non_negative"),
        "credit_accounts",
        "period_spent >= 0",
    )
    op.create_check_constraint(
        op.f("ck_credit_accounts_monthly_spend_limit_positive"),
        "credit_accounts",
        "monthly_spend_limit IS NULL OR monthly_spend_limit > 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_credit_accounts_monthly_spend_limit_positive"), "credit_accounts", type_="check"
    )
    op.drop_constraint(
        op.f("ck_credit_accounts_period_spent_non_negative"), "credit_accounts", type_="check"
    )
    op.drop_column("credit_accounts", "period_spent")
    op.drop_column("credit_accounts", "spend_period")
    op.drop_column("credit_accounts", "monthly_spend_limit")
