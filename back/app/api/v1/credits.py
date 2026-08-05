"""Credit balance, ledger, packages and the mock checkout flow."""

from __future__ import annotations

import hashlib
import hmac
import json
import time

from fastapi import APIRouter, Header, Request
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession, IdempotencyKey
from app.api.schemas.common import OkResponse, Page
from app.api.schemas.jobs import (
    CheckoutRequest,
    CheckoutResponse,
    CreditBalanceResponse,
    CreditPackageResponse,
    LedgerEntryResponse,
    RedeemCodeRequest,
    RedeemCodeResponse,
)
from app.config import get_settings
from app.domain.credits import redemption
from app.domain.credits import service as credits_service
from app.domain.errors import Conflict, NotFound, ValidationFailed
from app.models import CreditPackage, PaymentIntent, WebhookEvent
from app.models.base import new_id, utcnow

router = APIRouter(tags=["credits"])

# Rejecting old signatures blocks replay of a captured webhook body.
WEBHOOK_TOLERANCE_SECONDS = 300


@router.get("/credits/balance", response_model=CreditBalanceResponse)
def balance(user: CurrentUser, session: DbSession) -> CreditBalanceResponse:
    account = credits_service.get_or_create_account(session, user.id)
    session.commit()
    return CreditBalanceResponse(
        available=account.available_balance,
        reserved=account.reserved_balance,
        currency=account.currency,
    )


@router.get("/credits/ledger", response_model=Page[LedgerEntryResponse])
def ledger(
    user: CurrentUser, session: DbSession, cursor: str | None = None, limit: int = 20
) -> Page[LedgerEntryResponse]:
    credits_service.get_or_create_account(session, user.id)
    session.commit()
    entries = credits_service.list_ledger(session, user.id, cursor=cursor, limit=limit + 1)
    has_more = len(entries) > limit
    page = entries[:limit]
    return Page(
        items=[LedgerEntryResponse.model_validate(e) for e in page],
        next_cursor=page[-1].id if has_more and page else None,
        has_more=has_more,
    )


@router.get("/credits/packages", response_model=Page[CreditPackageResponse])
def packages(user: CurrentUser, session: DbSession) -> Page[CreditPackageResponse]:
    rows = session.scalars(
        select(CreditPackage)
        .where(CreditPackage.is_active.is_(True), CreditPackage.region == user.region)
        .order_by(CreditPackage.sort_order)
    )
    return Page(items=[CreditPackageResponse.model_validate(p) for p in rows])


@router.post("/credits/redeem", response_model=RedeemCodeResponse)
def redeem(payload: RedeemCodeRequest, user: CurrentUser, session: DbSession) -> RedeemCodeResponse:
    """Cashes in an invite/promo code for its face-value credits."""
    record = redemption.redeem(session, code=payload.code, user_id=user.id)
    account = credits_service.get_or_create_account(session, user.id)
    session.commit()
    return RedeemCodeResponse(
        credits_granted=record.credits, available_balance=account.available_balance
    )


@router.post("/credits/checkout", response_model=CheckoutResponse, status_code=201)
def checkout(
    payload: CheckoutRequest,
    user: CurrentUser,
    session: DbSession,
    idempotency_key: IdempotencyKey,
) -> CheckoutResponse:
    """Creates a payment intent.

    No credits are granted here. Only a verified webhook turns a payment into
    balance, so a user who abandons checkout is never charged or credited.
    """
    package = session.get(CreditPackage, payload.package_id)
    if package is None or not package.is_active:
        raise NotFound("套餐不存在。")

    key = idempotency_key or new_id("idk")
    existing = session.scalar(
        select(PaymentIntent).where(
            PaymentIntent.user_id == user.id, PaymentIntent.idempotency_key == key
        )
    )
    if existing is not None:
        return _checkout_response(existing)

    intent = PaymentIntent(
        user_id=user.id,
        package_id=package.id,
        provider="mock",
        external_reference=f"pi_mock_{new_id('ref')}",
        amount_minor=package.price_minor,
        currency=package.currency,
        idempotency_key=key,
    )
    session.add(intent)
    session.commit()
    return _checkout_response(intent)


@router.post("/webhooks/payments/mock", response_model=OkResponse)
async def payment_webhook(
    request: Request,
    session: DbSession,
    x_signature: str | None = Header(default=None, alias="X-Signature"),
    x_timestamp: str | None = Header(default=None, alias="X-Timestamp"),
) -> OkResponse:
    """Books a settled payment.

    Three separate protections apply: HMAC signature over the raw body, a
    timestamp window against replay, and a unique event id so repeated delivery
    of a genuine event credits the account exactly once.
    """
    raw_body = await request.body()
    _verify_signature(raw_body, x_signature, x_timestamp)

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise ValidationFailed("回调内容不是合法 JSON。") from exc

    event_id = str(payload.get("event_id") or "")
    if not event_id:
        raise ValidationFailed("缺少 event_id。")

    existing = session.scalar(
        select(WebhookEvent).where(
            WebhookEvent.provider == "mock", WebhookEvent.external_event_id == event_id
        )
    )
    if existing is not None:
        # Idempotent by design: acknowledge without re-booking.
        return OkResponse()

    session.add(
        WebhookEvent(
            provider="mock",
            external_event_id=event_id,
            event_type=str(payload.get("type") or "payment.succeeded"),
            payload_json=payload,
            created_at=utcnow(),
        )
    )

    reference = str(payload.get("external_reference") or "")
    intent = session.scalar(
        select(PaymentIntent).where(PaymentIntent.external_reference == reference)
    )
    if intent is None:
        raise NotFound("支付订单不存在。")

    if payload.get("type") == "payment.succeeded" and intent.status != "succeeded":
        package = session.get(CreditPackage, intent.package_id)
        if package is None:
            raise NotFound("套餐不存在。")
        credits_service.purchase(
            session,
            intent.user_id,
            package.credits + package.bonus_credits,
            payment_reference=intent.external_reference,
            metadata={"package_slug": package.slug, "amount_minor": intent.amount_minor},
        )
        intent.status = "succeeded"
        intent.settled_at = utcnow()

    session.commit()
    return OkResponse()


def sign_payload(raw_body: bytes, timestamp: str) -> str:
    """Shared by the mock checkout page and the verifier."""
    secret = get_settings().payment_webhook_secret.encode()
    message = timestamp.encode() + b"." + raw_body
    return hmac.new(secret, message, hashlib.sha256).hexdigest()


def _verify_signature(raw_body: bytes, signature: str | None, timestamp: str | None) -> None:
    if not signature or not timestamp:
        raise ValidationFailed("缺少签名。")
    try:
        sent_at = int(timestamp)
    except ValueError as exc:
        raise ValidationFailed("时间戳不合法。") from exc

    if abs(int(time.time()) - sent_at) > WEBHOOK_TOLERANCE_SECONDS:
        raise Conflict("回调时间戳超出允许范围。")

    expected = sign_payload(raw_body, timestamp)
    # Constant-time comparison so the endpoint cannot be used as an oracle.
    if not hmac.compare_digest(expected, signature):
        raise ValidationFailed("签名校验失败。")


def _checkout_response(intent: PaymentIntent) -> CheckoutResponse:
    settings = get_settings()
    return CheckoutResponse(
        payment_intent_id=intent.id,
        checkout_url=f"{settings.web_base_url}/billing/mock-checkout?ref={intent.external_reference}",
        external_reference=intent.external_reference,
        amount_minor=intent.amount_minor,
        currency=intent.currency,
    )
