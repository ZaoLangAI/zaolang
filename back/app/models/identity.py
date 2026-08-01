"""Users, profiles, preferences and social graph."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    ARRAY,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, id_column
from app.models.enums import Locale, Region, ThemePreference, UserRole, UserStatus


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[str] = id_column("usr")
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    identity_provider_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default=UserStatus.ACTIVE, nullable=False)
    # The platform is 18+; publishing and generation both gate on this.
    age_gate_confirmed_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    region: Mapped[str] = mapped_column(String(16), default=Region.CN, nullable=False)
    locale: Mapped[str] = mapped_column(String(16), default=Locale.ZH_CN, nullable=False)
    theme: Mapped[str] = mapped_column(String(16), default=ThemePreference.SYSTEM, nullable=False)
    roles: Mapped[list[str]] = mapped_column(
        ARRAY(String(32)), default=lambda: [UserRole.USER.value], nullable=False
    )
    suspended_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_login_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    profile: Mapped[Profile] = relationship(back_populates="user", uselist=False)

    __table_args__ = (Index("ix_users_status", "status"),)

    def has_role(self, role: str) -> bool:
        return role in self.roles

    @property
    def is_active(self) -> bool:
        return self.status == UserStatus.ACTIVE


class Profile(Base, TimestampMixin):
    __tablename__ = "profiles"

    id: Mapped[str] = id_column("prf")
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    display_name: Mapped[str] = mapped_column(String(80), nullable=False)
    handle: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    bio: Mapped[str | None] = mapped_column(Text, nullable=True)
    location: Mapped[str | None] = mapped_column(String(80), nullable=True)
    avatar_asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("assets.id", ondelete="SET NULL"), nullable=True
    )
    cover_asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("assets.id", ondelete="SET NULL"), nullable=True
    )
    public_profile: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notify_on_remix: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    reduce_motion: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    user: Mapped[User] = relationship(back_populates="profile")


class Follow(Base, TimestampMixin):
    __tablename__ = "follows"

    id: Mapped[str] = id_column("flw")
    follower_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    followed_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("follower_user_id", "followed_user_id", name="uq_follows_pair"),
        Index("ix_follows_followed_user_id", "followed_user_id"),
    )
