"""add episode external metrics

Latest play/like/comment/share snapshot per published post, pulled
periodically from Douyin/Kuaishou's own metrics endpoint
(`app.domain.distribution.service.pull_episode_metrics`, run off the new
`platform_distribution` Celery queue). One row per `(work_id, channel,
external_post_id)` — a pull upserts the existing row rather than growing a
time series, matching this phase's "basic counts, no deep history" scope.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "3c8e1f4a9d02"
down_revision: str | None = "7ab6fa2b7eed"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "episode_external_metrics",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("work_id", sa.String(length=40), nullable=False),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("external_post_id", sa.String(length=128), nullable=False),
        sa.Column("view_count", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("like_count", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("comment_count", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("share_count", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["work_id"],
            ["works.id"],
            name=op.f("fk_episode_external_metrics_work_id_works"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_episode_external_metrics")),
        sa.UniqueConstraint(
            "work_id",
            "channel",
            "external_post_id",
            name="uq_episode_external_metrics_work_channel_post",
        ),
    )
    op.create_index(
        "ix_episode_external_metrics_work_id",
        "episode_external_metrics",
        ["work_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_episode_external_metrics_work_id", table_name="episode_external_metrics")
    op.drop_table("episode_external_metrics")
