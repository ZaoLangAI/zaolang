"""One-time marketplace unlocks for paid works and skills."""

from __future__ import annotations

from sqlalchemy import ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, id_column
from app.models.enums import AccessSubjectType


class AccessGrant(Base, TimestampMixin):
    """A buyer's receipt that they paid (or were waived) for one subject.

    Unique on `(buyer, subject_type, subject_id)` so a concurrent double-unlock
    has exactly one winner. Price fields are snapshots: later list-price
    changes never rewrite a grant that already landed.
    """

    __tablename__ = "access_grants"

    id: Mapped[str] = id_column("agr")
    buyer_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    seller_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    subject_type: Mapped[str] = mapped_column(
        String(16), default=AccessSubjectType.WORK, nullable=False
    )
    subject_id: Mapped[str] = mapped_column(String(40), nullable=False)
    price_credits: Mapped[int] = mapped_column(Integer, nullable=False)
    platform_fee_credits: Mapped[int] = mapped_column(Integer, nullable=False)
    seller_net_credits: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "buyer_user_id",
            "subject_type",
            "subject_id",
            name="uq_access_grants_buyer_subject",
        ),
        Index("ix_access_grants_seller", "seller_user_id"),
        Index("ix_access_grants_subject", "subject_type", "subject_id"),
    )
