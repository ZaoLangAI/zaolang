"""Mock payment checkout and webhook booking.

Money is the one place where a duplicate delivery, a replayed body or a forged
signature must all fail closed, so each protection gets its own test.
"""

from __future__ import annotations

import json
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.credits import sign_payload
from app.domain.credits import service as credits_service
from app.models import CreditLedgerEntry, CreditPackage, PaymentIntent, User
from app.models.enums import LedgerEntryType
from tests.conftest import auth_header

WEBHOOK_URL = "/v1/webhooks/payments/mock"


@pytest.fixture
def package(db: Session) -> CreditPackage:
    pkg = CreditPackage(
        slug="starter",
        region="CN",
        currency="CNY",
        price_minor=1_900,
        credits=200,
        bonus_credits=20,
        is_active=True,
        sort_order=1,
    )
    db.add(pkg)
    db.flush()
    return pkg


def _checkout(client: TestClient, user: User, package: CreditPackage, key: str = "idk-1") -> dict:
    response = client.post(
        "/v1/credits/checkout",
        json={"package_id": package.id},
        headers={**auth_header(user), "Idempotency-Key": key},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _deliver(client: TestClient, payload: dict, *, timestamp: int | None = None) -> object:
    raw = json.dumps(payload).encode()
    stamp = str(timestamp if timestamp is not None else int(time.time()))
    return client.post(
        WEBHOOK_URL,
        content=raw,
        headers={
            "X-Signature": sign_payload(raw, stamp),
            "X-Timestamp": stamp,
            "Content-Type": "application/json",
        },
    )


def _succeeded(reference: str, event_id: str = "evt_1") -> dict:
    return {"event_id": event_id, "type": "payment.succeeded", "external_reference": reference}


def test_checkout_creates_an_intent_without_granting_credits(
    client: TestClient, db: Session, author: User, package: CreditPackage
) -> None:
    """A user who abandons the payment page must not end up with balance."""
    before = credits_service.get_or_create_account(db, author.id).available_balance
    body = _checkout(client, author, package)

    assert body["external_reference"].startswith("pi_mock_")
    assert credits_service.get_or_create_account(db, author.id).available_balance == before


def test_checkout_is_idempotent(client: TestClient, author: User, package: CreditPackage) -> None:
    first = _checkout(client, author, package, key="same")
    second = _checkout(client, author, package, key="same")
    assert first["payment_intent_id"] == second["payment_intent_id"]


def test_checkout_for_an_unknown_package_is_refused(client: TestClient, author: User) -> None:
    response = client.post(
        "/v1/credits/checkout",
        json={"package_id": "cpk_nope"},
        headers={**auth_header(author), "Idempotency-Key": "idk-x"},
    )
    assert response.status_code == 404


def test_a_verified_webhook_credits_the_account(
    client: TestClient, db: Session, author: User, package: CreditPackage
) -> None:
    before = credits_service.get_or_create_account(db, author.id).available_balance
    intent = _checkout(client, author, package)

    response = _deliver(client, _succeeded(intent["external_reference"]))
    assert response.status_code == 200, response.text

    after = credits_service.get_or_create_account(db, author.id).available_balance
    assert after == before + package.credits + package.bonus_credits


def test_the_bonus_credits_are_included(
    client: TestClient, db: Session, author: User, package: CreditPackage
) -> None:
    intent = _checkout(client, author, package)
    _deliver(client, _succeeded(intent["external_reference"]))

    account = credits_service.get_or_create_account(db, author.id)
    entry = db.scalar(
        select(CreditLedgerEntry).where(
            CreditLedgerEntry.account_id == account.id,
            CreditLedgerEntry.type == LedgerEntryType.PURCHASE,
        )
    )
    assert entry is not None
    assert entry.amount == package.credits + package.bonus_credits


def test_redelivery_of_the_same_event_credits_only_once(
    client: TestClient, db: Session, author: User, package: CreditPackage
) -> None:
    """Payment providers retry until they see a 2xx, so the second delivery of
    a genuine event is normal traffic, not an attack."""
    intent = _checkout(client, author, package)
    before = credits_service.get_or_create_account(db, author.id).available_balance

    for _ in range(3):
        assert _deliver(client, _succeeded(intent["external_reference"])).status_code == 200

    after = credits_service.get_or_create_account(db, author.id).available_balance
    assert after == before + package.credits + package.bonus_credits


def test_two_distinct_events_for_one_intent_credit_only_once(
    client: TestClient, db: Session, author: User, package: CreditPackage
) -> None:
    """Different event ids get past the webhook dedupe, so the intent's own
    status has to be the second line of defence."""
    intent = _checkout(client, author, package)
    before = credits_service.get_or_create_account(db, author.id).available_balance

    _deliver(client, _succeeded(intent["external_reference"], event_id="evt_a"))
    _deliver(client, _succeeded(intent["external_reference"], event_id="evt_b"))

    after = credits_service.get_or_create_account(db, author.id).available_balance
    assert after == before + package.credits + package.bonus_credits


def test_a_forged_signature_is_rejected(
    client: TestClient, db: Session, author: User, package: CreditPackage
) -> None:
    intent = _checkout(client, author, package)
    before = credits_service.get_or_create_account(db, author.id).available_balance

    raw = json.dumps(_succeeded(intent["external_reference"])).encode()
    response = client.post(
        WEBHOOK_URL,
        content=raw,
        headers={"X-Signature": "0" * 64, "X-Timestamp": str(int(time.time()))},
    )

    assert response.status_code == 422
    assert credits_service.get_or_create_account(db, author.id).available_balance == before


def test_a_body_altered_after_signing_is_rejected(
    client: TestClient, author: User, package: CreditPackage
) -> None:
    """The signature covers the raw body, so swapping the reference invalidates
    it."""
    intent = _checkout(client, author, package)
    signed = json.dumps(_succeeded(intent["external_reference"])).encode()
    stamp = str(int(time.time()))
    signature = sign_payload(signed, stamp)

    tampered = json.dumps(_succeeded("pi_mock_someone_else")).encode()
    response = client.post(
        WEBHOOK_URL,
        content=tampered,
        headers={"X-Signature": signature, "X-Timestamp": stamp},
    )
    assert response.status_code == 422


def test_an_unsigned_callback_is_rejected(client: TestClient) -> None:
    response = client.post(WEBHOOK_URL, json=_succeeded("pi_mock_x"))
    assert response.status_code == 422


def test_a_stale_timestamp_is_rejected(
    client: TestClient, author: User, package: CreditPackage
) -> None:
    """A correctly signed body captured hours ago must not still be replayable."""
    intent = _checkout(client, author, package)
    response = _deliver(
        client, _succeeded(intent["external_reference"]), timestamp=int(time.time()) - 3_600
    )
    assert response.status_code == 409


def test_a_future_timestamp_is_rejected(
    client: TestClient, author: User, package: CreditPackage
) -> None:
    intent = _checkout(client, author, package)
    response = _deliver(
        client, _succeeded(intent["external_reference"]), timestamp=int(time.time()) + 3_600
    )
    assert response.status_code == 409


def test_a_callback_without_an_event_id_is_rejected(client: TestClient) -> None:
    response = _deliver(client, {"type": "payment.succeeded", "external_reference": "x"})
    assert response.status_code == 422


def test_a_callback_for_an_unknown_intent_is_rejected(client: TestClient) -> None:
    response = _deliver(client, _succeeded("pi_mock_does_not_exist"))
    assert response.status_code == 404


def test_a_failed_payment_does_not_credit_anything(
    client: TestClient, db: Session, author: User, package: CreditPackage
) -> None:
    intent = _checkout(client, author, package)
    before = credits_service.get_or_create_account(db, author.id).available_balance

    response = _deliver(
        client,
        {
            "event_id": "evt_failed",
            "type": "payment.failed",
            "external_reference": intent["external_reference"],
        },
    )
    assert response.status_code == 200
    assert credits_service.get_or_create_account(db, author.id).available_balance == before

    row = db.scalar(
        select(PaymentIntent).where(
            PaymentIntent.external_reference == intent["external_reference"]
        )
    )
    assert row is not None
    assert row.status != "succeeded"


def test_the_ledger_shows_the_purchase(
    client: TestClient, author: User, package: CreditPackage
) -> None:
    intent = _checkout(client, author, package)
    _deliver(client, _succeeded(intent["external_reference"]))

    response = client.get("/v1/credits/ledger", headers=auth_header(author))
    assert response.status_code == 200
    types = [item["type"] for item in response.json()["items"]]
    assert LedgerEntryType.PURCHASE.value in types
