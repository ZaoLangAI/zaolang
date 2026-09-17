"""User-published learning posts, pending review before they go public."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, id_column
from app.models.enums import LearnPostLevel, LearnPostStatus


class LearnPost(Base, TimestampMixin):
    """一条图文教程投稿。改内容一律回到 PENDING 重新过审（在 domain 层强制），
    这里只负责把审核决定（reviewed_by/at、reject_reason）与发布时间落库。"""

    __tablename__ = "learn_posts"

    id: Mapped[str] = id_column("lrn")
    author_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(80), nullable=False)
    summary: Mapped[str] = mapped_column(String(160), nullable=False)
    level: Mapped[str] = mapped_column(String(24), default=LearnPostLevel.BEGINNER, nullable=False)
    cover_asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("assets.id", ondelete="SET NULL"), nullable=True
    )
    body_markdown: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(24), default=LearnPostStatus.PENDING, nullable=False)
    reject_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_learn_posts_status_published", "status", "published_at"),
        Index("ix_learn_posts_author", "author_user_id"),
    )
