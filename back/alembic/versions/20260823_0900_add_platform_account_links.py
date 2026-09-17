"""add platform account links

One row per creator's OAuth grant to an external short-video platform
(Douyin/Kuaishou today, extensible to more via `app.domain.distribution`'s
`PlatformClient` registry). A user can link more than one account on the
same channel (hence the three-column unique constraint on
`(user_id, channel, external_account_id)` rather than `(user_id, channel)`),
but never the same external account twice.

`access_token_encrypted`/`refresh_token_encrypted` hold Fernet ciphertext
only — see `app.domain.distribution.crypto`. Disconnecting a link tombstones
it (`status=revoked` + `revoked_at`) rather than deleting the row, matching
this codebase's general preference for keeping history over hard deletes.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "7ab6fa2b7eed"
down_revision: str | None = "9af5e04a2bba"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "platform_account_links",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("user_id", sa.String(length=40), nullable=False),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("external_account_id", sa.String(length=128), nullable=False),
        sa.Column("external_account_label", sa.String(length=255), nullable=True),
        sa.Column("access_token_encrypted", sa.String(length=2048), nullable=False),
        sa.Column("refresh_token_encrypted", sa.String(length=2048), nullable=True),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scopes_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="active", nullable=False),
        sa.Column(
            "connected_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_refreshed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_platform_account_links_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_platform_account_links")),
        sa.UniqueConstraint(
            "user_id",
            "channel",
            "external_account_id",
            name="uq_platform_account_links_user_channel_account",
        ),
    )
    op.create_index(
        "ix_platform_account_links_user_channel",
        "platform_account_links",
        ["user_id", "channel"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_platform_account_links_user_channel", table_name="platform_account_links")
    op.drop_table("platform_account_links")
