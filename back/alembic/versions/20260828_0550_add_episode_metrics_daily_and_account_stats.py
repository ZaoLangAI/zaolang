"""add episode metrics daily and account stats

Two new day-by-day snapshot tables so the drama-series analytics dashboard
can plot real trend lines (`app.domain.distribution.service.
series_metrics_timeseries` / `series_metrics_period_comparison`) — something
`episode_external_metrics`'s upsert-in-place shape never allowed. Also adds
best-effort `finish_rate_bp`/`avg_play_duration_ms` columns to the existing
latest-snapshot table so the single-episode panel can surface them too.

Revision ID: 582b6e10168d
Revises: 899ea8654304
Create Date: 2026-08-28 05:50:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "582b6e10168d"
down_revision: str | None = "899ea8654304"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "episode_external_metrics", sa.Column("finish_rate_bp", sa.BigInteger(), nullable=True)
    )
    op.add_column(
        "episode_external_metrics",
        sa.Column("avg_play_duration_ms", sa.BigInteger(), nullable=True),
    )

    op.create_table(
        "episode_external_metric_daily",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("work_id", sa.String(length=40), nullable=False),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("external_post_id", sa.String(length=128), nullable=False),
        sa.Column("metric_date", sa.Date(), nullable=False),
        sa.Column("view_count", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("like_count", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("comment_count", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("share_count", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("finish_rate_bp", sa.BigInteger(), nullable=True),
        sa.Column("avg_play_duration_ms", sa.BigInteger(), nullable=True),
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
            name=op.f("fk_episode_external_metric_daily_work_id_works"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_episode_external_metric_daily")),
        sa.UniqueConstraint(
            "work_id",
            "channel",
            "external_post_id",
            "metric_date",
            name="uq_episode_external_metric_daily_work_channel_post_date",
        ),
    )
    op.create_index(
        "ix_episode_external_metric_daily_work_date",
        "episode_external_metric_daily",
        ["work_id", "metric_date"],
        unique=False,
    )

    op.create_table(
        "platform_account_daily_stats",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("link_id", sa.String(length=40), nullable=False),
        sa.Column("metric_date", sa.Date(), nullable=False),
        sa.Column("follower_count", sa.BigInteger(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["link_id"],
            ["platform_account_links.id"],
            name=op.f("fk_platform_account_daily_stats_link_id_platform_account_links"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_platform_account_daily_stats")),
        sa.UniqueConstraint(
            "link_id", "metric_date", name="uq_platform_account_daily_stats_link_date"
        ),
    )


def downgrade() -> None:
    op.drop_table("platform_account_daily_stats")
    op.drop_index(
        "ix_episode_external_metric_daily_work_date", table_name="episode_external_metric_daily"
    )
    op.drop_table("episode_external_metric_daily")
    op.drop_column("episode_external_metrics", "avg_play_duration_ms")
    op.drop_column("episode_external_metrics", "finish_rate_bp")
