"""record provider spend in micro-USD and drop the redundant agent model pin

Two related changes to how model cost is tracked.

`cost_minor` counts whole cents, which cannot represent what vendors actually
charge: $0.00286 per image rounds to zero, so every image call has been
recorded as free. The new `cost_micro_usd` columns hold 1e-6 USD integers,
where that price is exactly 2_860. They sit *beside* `cost_minor` rather than
replacing it — the credit ledger settles in minor units and must not move.

Existing rows keep 0, meaning "we never priced this", which is honest: the
prices needed to backfill them were not configured at the time and inventing
them now would fabricate a spend history.

`agent_profiles.model` goes away because an `llm_providers` endpoint now
declares exactly one model, so the profile's endpoint binding already names
it. Keeping both would let them drift, and would force a backup endpoint to
carry an identical model id — defeating the point of having a backup.

Revision ID: c4a7f0b2e5d8
Revises: b3d6e2f9c1a4
Create Date: 2026-08-15 18:00:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c4a7f0b2e5d8"
down_revision: str | None = "b3d6e2f9c1a4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_runs",
        sa.Column("cost_micro_usd", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.add_column(
        "provider_attempts",
        sa.Column("cost_micro_usd", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.add_column(
        "provider_stats",
        sa.Column("total_cost_micro_usd", sa.BigInteger(), nullable=False, server_default="0"),
    )
    # The default exists only so the backfill of existing rows is not NULL;
    # the ORM always supplies a value, and leaving it in place would let a
    # future insert that forgets the column silently record a spend of zero.
    op.alter_column("agent_runs", "cost_micro_usd", server_default=None)
    op.alter_column("provider_attempts", "cost_micro_usd", server_default=None)
    op.alter_column("provider_stats", "total_cost_micro_usd", server_default=None)

    op.drop_column("agent_profiles", "model")


def downgrade() -> None:
    op.add_column("agent_profiles", sa.Column("model", sa.String(length=160), nullable=True))
    # Restores the pin from whatever the bound endpoint declares, which is
    # where it came from in the first place.
    op.execute(
        """
        UPDATE agent_profiles AS p
        SET model = e.value ->> 'model'
        FROM platform_configs AS c,
             LATERAL jsonb_each(c.value_json -> 'endpoints') AS e(key, value)
        WHERE c.key = 'llm_providers'
          AND c.is_active
          AND e.key = p.default_endpoint_id
        """
    )
    op.drop_column("provider_stats", "total_cost_micro_usd")
    op.drop_column("provider_attempts", "cost_micro_usd")
    op.drop_column("agent_runs", "cost_micro_usd")
