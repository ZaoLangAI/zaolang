"""Credit accounts and the append-only ledger.

Two invariants are enforced in the schema itself rather than in code:

* A job can be captured at most once — `uq_credit_ledger_job_type` makes a second
  `capture` row for the same job impossible.
* A Stripe/mock payment event can only be booked once — `uq_credit_ledger_payment`
  covers the payment reference.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, id_column
from app.models.enums import RedemptionCodeKind


class CreditAccount(Base, TimestampMixin):
    __tablename__ = "credit_accounts"

    id: Mapped[str] = id_column("cra")
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    currency: Mapped[str] = mapped_column(String(16), default="CREDIT", nullable=False)
    available_balance: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    reserved_balance: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    # Optimistic lock. Every mutation bumps it inside a conditional UPDATE, so
    # two concurrent reserves cannot both read the same balance and succeed.
    version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    __table_args__ = (
        CheckConstraint("available_balance >= 0", name="available_balance_non_negative"),
        CheckConstraint("reserved_balance >= 0", name="reserved_balance_non_negative"),
    )


class CreditLedgerEntry(Base):
    __tablename__ = "credit_ledger_entries"

    id: Mapped[str] = id_column("led")
    account_id: Mapped[str] = mapped_column(
        ForeignKey("credit_accounts.id", ondelete="RESTRICT"), nullable=False
    )
    type: Mapped[str] = mapped_column(String(24), nullable=False)
    # Signed delta applied to available balance; reserved movement is derived.
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    balance_after: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reserved_after: Mapped[int] = mapped_column(BigInteger, nullable=False)
    job_id: Mapped[str | None] = mapped_column(
        ForeignKey("generation_jobs.id", ondelete="SET NULL"), nullable=True
    )
    payment_reference: Mapped[str | None] = mapped_column(String(160), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(160), nullable=True)
    # Mandatory for manual adjustments made from the back office.
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(default=dict, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("job_id", "type", name="uq_credit_ledger_job_type"),
        UniqueConstraint("payment_reference", name="uq_credit_ledger_payment"),
        UniqueConstraint("idempotency_key", name="uq_credit_ledger_idempotency"),
        Index("ix_credit_ledger_account_created", "account_id", "created_at"),
        Index("ix_credit_ledger_type", "type"),
    )


class CreditPackage(Base, TimestampMixin):
    __tablename__ = "credit_packages"

    id: Mapped[str] = id_column("pkg")
    slug: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    credits: Mapped[int] = mapped_column(Integer, nullable=False)
    bonus_credits: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Minor units (cents / 分 / 円). Never a float.
    price_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False)
    region: Mapped[str] = mapped_column(String(16), nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class PaymentIntent(Base, TimestampMixin):
    """Checkout session tracked on our side.

    The payment platform's balance is never treated as generation balance; a
    successful payment only becomes credits via a `purchase` ledger entry.
    """

    __tablename__ = "payment_intents"

    id: Mapped[str] = id_column("pay")
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    package_id: Mapped[str] = mapped_column(
        ForeignKey("credit_packages.id", ondelete="RESTRICT"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(32), default="mock", nullable=False)
    external_reference: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="pending", nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    settled_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key", name="uq_payment_intents_idempotency"),
    )


class WebhookEvent(Base):
    """Replay guard for inbound webhooks.

    The provider may deliver the same event many times; the unique event id is
    what makes repeated delivery safe.
    """

    __tablename__ = "webhook_events"

    id: Mapped[str] = id_column("whk")
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    external_event_id: Mapped[str] = mapped_column(String(160), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(nullable=False)
    processed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("provider", "external_event_id", name="uq_webhook_events_external"),
    )


class RedemptionCode(Base, TimestampMixin):
    """An operator-minted code worth a fixed number of credits.

    `max_uses` covers both shapes with one table: an invite code is `max_uses
    == 1`, a broadcast promo code is `max_uses > 1`. Either way each user can
    redeem it only once — enforced by `uq_redemption_records_code_user` on
    the record below, not by anything here.
    """

    __tablename__ = "redemption_codes"

    id: Mapped[str] = id_column("rdc")
    code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    kind: Mapped[str] = mapped_column(String(16), default=RedemptionCodeKind.PROMO, nullable=False)
    credits: Mapped[int] = mapped_column(Integer, nullable=False)
    max_uses: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    used_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        CheckConstraint("credits > 0", name="credits_positive"),
        CheckConstraint("max_uses > 0", name="max_uses_positive"),
    )


class RedemptionRecord(Base):
    """One successful redemption. Append-only, like the credit ledger it feeds."""

    __tablename__ = "redemption_records"

    id: Mapped[str] = id_column("rdr")
    code_id: Mapped[str] = mapped_column(
        ForeignKey("redemption_codes.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    credits: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("code_id", "user_id", name="uq_redemption_records_code_user"),
        Index("ix_redemption_records_user", "user_id"),
    )
