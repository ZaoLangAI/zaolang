"""track who declared an asset consent, its revocation, and real-person uploads

Revision ID: e5a9c3f1b7d2
Revises: d4e8b2c6a170
Create Date: 2026-09-14 13:00:00.000000+00:00

Voice-clone samples and real-person references now need an active consent
before a generation job may use them (`app.domain.consent.service`). A
consent records who declared it and when it was revoked — the row stays, so
the audit trail still resolves — and an upload carries the uploader's
declaration that it depicts a real person through to its asset.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e5a9c3f1b7d2"
down_revision: str | None = "d4e8b2c6a170"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "asset_consents", sa.Column("declared_by_user_id", sa.String(length=40), nullable=True)
    )
    op.create_foreign_key(
        "fk_asset_consents_declared_by_user_id_users",
        "asset_consents",
        "users",
        ["declared_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_asset_consents_declared_by_user_id", "asset_consents", ["declared_by_user_id"]
    )
    op.add_column(
        "asset_consents", sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "assets",
        sa.Column("depicts_real_person", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "upload_sessions",
        sa.Column("depicts_real_person", sa.Boolean(), server_default=sa.false(), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("upload_sessions", "depicts_real_person")
    op.drop_column("assets", "depicts_real_person")
    op.drop_column("asset_consents", "revoked_at")
    op.drop_index("ix_asset_consents_declared_by_user_id", table_name="asset_consents")
    op.drop_constraint(
        "fk_asset_consents_declared_by_user_id_users", "asset_consents", type_="foreignkey"
    )
    op.drop_column("asset_consents", "declared_by_user_id")
