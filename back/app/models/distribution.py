"""One creator's OAuth authorization to a Douyin/Kuaishou-style platform.

Kept out of `app/models/platform.py` on purpose: that module holds moderation/
config-centre/ops records, an unrelated meaning of "platform". This is about
a per-user, per-channel connection to an *external* short-video platform.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, UniqueConstraint, func
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
    external_post_id)` — a pull upserts in place rather than growing a time
    series, matching the "basic metrics, no deep history" scope this phase
    was scoped to (see `zaolang-editor-drama` / the distribution plan doc).
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
