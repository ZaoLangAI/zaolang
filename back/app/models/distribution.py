"""One creator's OAuth authorization to a Douyin/Kuaishou-style platform.

Kept out of `app/models/platform.py` on purpose: that module holds moderation/
config-centre/ops records, an unrelated meaning of "platform". This is about
a per-user, per-channel connection to an *external* short-video platform.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, id_column
from app.models.enums import PlatformAccountLinkStatus


class PlatformAccountLink(Base, TimestampMixin):
    """A creator's OAuth grant on one channel, tokens encrypted at rest.

    `access_token_encrypted`/`refresh_token_encrypted` are only ever decrypted
    right before an outbound platform API call (see
    `app.domain.distribution.crypto`) — nothing persists the plaintext value,
    and nothing may log it.
    """

    __tablename__ = "platform_account_links"

    id: Mapped[str] = id_column("pal")
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    # The platform's own account identifier (Douyin/Kuaishou `open_id`).
    external_account_id: Mapped[str] = mapped_column(String(128), nullable=False)
    external_account_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    access_token_encrypted: Mapped[str] = mapped_column(String(2048), nullable=False)
    refresh_token_encrypted: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    token_expires_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    scopes_json: Mapped[list[Any]] = mapped_column(default=list, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16),
        default=PlatformAccountLinkStatus.ACTIVE,
        server_default=PlatformAccountLinkStatus.ACTIVE.value,
        nullable=False,
    )
    connected_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_refreshed_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Tombstone field, not a delete: `disconnect()` sets this + `status` to
    # `REVOKED` and the row stays for history (see `zaolang-data-model`).
    revoked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "channel",
            "external_account_id",
            name="uq_platform_account_links_user_channel_account",
        ),
        Index("ix_platform_account_links_user_channel", "user_id", "channel"),
    )


class EpisodeExternalMetric(Base, TimestampMixin):
    """Latest play/like/comment/share snapshot for one published post.

    Anchored on `Work` (not `DramaEpisode`): analytics only make sense once
    something has actually been pushed externally, and `PublicationIntent`
    already anchors on `Work` too. One row per `(work_id, channel,
    external_post_id)` — a pull upserts in place, so this table alone still
    has no history. `EpisodeExternalMetricDaily` is the companion table that
    keeps a day-by-day trail for trend charts; this one stays as the cheap
    "latest snapshot" read path nothing else needs to change for.
    """

    __tablename__ = "episode_external_metrics"

    id: Mapped[str] = id_column("eem")
    work_id: Mapped[str] = mapped_column(ForeignKey("works.id", ondelete="CASCADE"), nullable=False)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    external_post_id: Mapped[str] = mapped_column(String(128), nullable=False)
    view_count: Mapped[int] = mapped_column(
        BigInteger, default=0, server_default="0", nullable=False
    )
    like_count: Mapped[int] = mapped_column(
        BigInteger, default=0, server_default="0", nullable=False
    )
    comment_count: Mapped[int] = mapped_column(
        BigInteger, default=0, server_default="0", nullable=False
    )
    share_count: Mapped[int] = mapped_column(
        BigInteger, default=0, server_default="0", nullable=False
    )
    # Basis points (0-10000) rather than a float ratio — this schema never
    # uses `Float` (see `zaolang-data-model` / `app.models.base`'s module
    # docstring), and best-effort besides: neither platform client's raw
    # response shape for this field is confirmed against live docs.
    finish_rate_bp: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    avg_play_duration_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    fetched_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "work_id",
            "channel",
            "external_post_id",
            name="uq_episode_external_metrics_work_channel_post",
        ),
        Index("ix_episode_external_metrics_work_id", "work_id"),
    )


class EpisodeExternalMetricDaily(Base, TimestampMixin):
    """One row per `(work_id, channel, external_post_id, metric_date)` —
    the history `EpisodeExternalMetric` deliberately doesn't keep. A pull
    upserts in place for the current UTC day (repeated same-day pulls never
    grow beyond one row per post per day), so `metric_date` is a clean
    x-axis for a trend chart: the point-in-time cumulative total for that
    post as of that day, not a daily delta.
    """

    __tablename__ = "episode_external_metric_daily"

    id: Mapped[str] = id_column("eemd")
    work_id: Mapped[str] = mapped_column(ForeignKey("works.id", ondelete="CASCADE"), nullable=False)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    external_post_id: Mapped[str] = mapped_column(String(128), nullable=False)
    metric_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    view_count: Mapped[int] = mapped_column(
        BigInteger, default=0, server_default="0", nullable=False
    )
    like_count: Mapped[int] = mapped_column(
        BigInteger, default=0, server_default="0", nullable=False
    )
    comment_count: Mapped[int] = mapped_column(
        BigInteger, default=0, server_default="0", nullable=False
    )
    share_count: Mapped[int] = mapped_column(
        BigInteger, default=0, server_default="0", nullable=False
    )
    finish_rate_bp: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    avg_play_duration_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    fetched_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "work_id",
            "channel",
            "external_post_id",
            "metric_date",
            name="uq_episode_external_metric_daily_work_channel_post_date",
        ),
        Index("ix_episode_external_metric_daily_work_date", "work_id", "metric_date"),
    )


class PlatformAccountDailyStat(Base, TimestampMixin):
    """One row per `(link_id, metric_date)` — a day's follower-count
    snapshot for a linked account, same upsert-per-day shape as
    `EpisodeExternalMetricDaily`. `follower_count` is best-effort: neither
    platform client's account-info endpoint is confirmed against live docs,
    so a pull that can't parse it leaves this `NULL` rather than guessing.
    """

    __tablename__ = "platform_account_daily_stats"

    id: Mapped[str] = id_column("pads")
    link_id: Mapped[str] = mapped_column(
        ForeignKey("platform_account_links.id", ondelete="CASCADE"), nullable=False
    )
    metric_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    follower_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    fetched_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "link_id", "metric_date", name="uq_platform_account_daily_stats_link_date"
        ),
    )
