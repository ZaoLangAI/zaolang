"""Redemption codes: domain rules, the consumer redeem endpoint, registration
invite-code integration and admin CRUD."""

from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.domain.credits import redemption
from app.domain.credits import service as credits_service
from app.domain.errors import Conflict, NotFound
from app.models import RedemptionCode, User
from app.models.base import utcnow
from app.models.enums import RedemptionCodeKind
from tests.conftest import admin_header, auth_header

# --- domain: redemption.py --------------------------------------------------


def test_redeeming_a_code_grants_credits_and_bumps_used_count(db: Session, author: User) -> None:
    code = redemption.create_code(
        db, kind=RedemptionCodeKind.PROMO, credits=200, actor_user_id=author.id
    )
    db.commit()
    before = credits_service.get_or_create_account(db, author.id).available_balance

    record = redemption.redeem(db, code=code.code, user_id=author.id)
    db.commit()

    db.expire_all()
    after = credits_service.get_or_create_account(db, author.id).available_balance
    assert after == before + 200
    assert record.credits == 200
    reloaded = db.get(RedemptionCode, code.id)
    assert reloaded is not None
    assert reloaded.used_count == 1


def test_redeeming_the_same_code_twice_by_the_same_user_fails_closed(
    db: Session, author: User
) -> None:
    code = redemption.create_code(
        db, kind=RedemptionCodeKind.PROMO, credits=100, max_uses=5, actor_user_id=author.id
    )
    db.commit()

    redemption.redeem(db, code=code.code, user_id=author.id)
    db.commit()

    with pytest.raises(Conflict):
        redemption.redeem(db, code=code.code, user_id=author.id)


def test_redeeming_past_the_use_cap_is_refused(db: Session, author: User, remixer: User) -> None:
    code = redemption.create_code(
        db, kind=RedemptionCodeKind.PROMO, credits=100, max_uses=1, actor_user_id=author.id
    )
    db.commit()

    redemption.redeem(db, code=code.code, user_id=author.id)
    db.commit()

    with pytest.raises(Conflict):
        redemption.redeem(db, code=code.code, user_id=remixer.id)


def test_redeeming_an_expired_code_is_refused(db: Session, author: User) -> None:
    code = redemption.create_code(
        db,
        kind=RedemptionCodeKind.INVITE,
        credits=100,
        expires_at=utcnow() - dt.timedelta(days=1),
        actor_user_id=author.id,
    )
    db.commit()

    with pytest.raises(Conflict):
        redemption.redeem(db, code=code.code, user_id=author.id)


def test_redeeming_a_deactivated_code_is_refused(db: Session, author: User) -> None:
    code = redemption.create_code(
        db, kind=RedemptionCodeKind.PROMO, credits=100, actor_user_id=author.id
    )
    redemption.deactivate_code(db, code=code)
    db.commit()

    with pytest.raises(Conflict):
        redemption.redeem(db, code=code.code, user_id=author.id)


def test_redeeming_an_unknown_code_reports_not_found(db: Session, author: User) -> None:
    with pytest.raises(NotFound):
        redemption.redeem(db, code="DOESNOTEXIST", user_id=author.id)


# --- consumer endpoint: POST /v1/credits/redeem -----------------------------


def test_the_redeem_endpoint_grants_credits_to_the_caller(
    client: TestClient, db: Session, author: User
) -> None:
    code = redemption.create_code(
        db, kind=RedemptionCodeKind.PROMO, credits=150, actor_user_id=author.id
    )
    db.commit()

    response = client.post(
        "/v1/credits/redeem", json={"code": code.code}, headers=auth_header(author)
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["credits_granted"] == 150
    assert body["available_balance"] >= 150


def test_the_redeem_endpoint_rejects_an_unknown_code(client: TestClient, author: User) -> None:
    response = client.post(
        "/v1/credits/redeem", json={"code": "NOPE1234"}, headers=auth_header(author)
    )
    assert response.status_code == 404


# --- registration: optional invite code -------------------------------------


def test_registering_with_an_invalid_invite_code_is_refused_before_any_commit(
    client: TestClient,
) -> None:
    """`redemption.redeem()` runs before `register()`'s single `session.commit()`,
    so a bad code surfaces as this 404 instead of ever reaching the database."""
    response = client.post(
        "/v1/auth/register",
        json={
            "email": "invited_bad@example.com",
            "password": "Zaolang2026",
            "display_name": "受邀用户",
            "handle": "invited_bad",
            "age_confirmed": True,
            "invite_code": "NOSUCHCODE",
        },
    )
    assert response.status_code == 404


def test_registering_with_a_valid_invite_code_grants_extra_credits(
    client: TestClient, db: Session, admin: User
) -> None:
    code = redemption.create_code(
        db, kind=RedemptionCodeKind.INVITE, credits=500, actor_user_id=admin.id
    )
    db.commit()

    response = client.post(
        "/v1/auth/register",
        json={
            "email": "invited_good@example.com",
            "password": "Zaolang2026",
            "display_name": "受邀用户",
            "handle": "invited_good",
            "age_confirmed": True,
            "invite_code": code.code,
        },
    )
    assert response.status_code == 201, response.text
    token = response.json()["access_token"]

    me = client.get("/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    starter_only = credits_service.SIGNUP_GRANT_CREDITS
    assert me.json()["available_credits"] == starter_only + 500

    db.expire_all()
    reloaded = db.get(RedemptionCode, code.id)
    assert reloaded is not None
    assert reloaded.used_count == 1


# --- admin CRUD --------------------------------------------------------------


def test_admin_can_create_list_and_deactivate_a_code(
    client: TestClient, db: Session, admin: User
) -> None:
    created = client.post(
        "/v1/admin/redemption-codes",
        json={
            "kind": "promo",
            "credits": 300,
            "max_uses": 3,
            "reason": "市场活动发码",
            "confirm": True,
        },
        headers=admin_header(admin),
    )
    assert created.status_code == 200, created.text
    code_id = created.json()["id"]
    assert created.json()["used_count"] == 0

    listed = client.get("/v1/admin/redemption-codes", headers=admin_header(admin))
    assert listed.status_code == 200
    assert any(item["id"] == code_id for item in listed.json()["items"])

    deactivated = client.post(
        f"/v1/admin/redemption-codes/{code_id}/deactivate",
        json={"reason": "码已泄露，停止使用", "confirm": True},
        headers=admin_header(admin),
    )
    assert deactivated.status_code == 200
    assert deactivated.json()["is_active"] is False


def test_creating_a_code_without_confirmation_is_refused(client: TestClient, admin: User) -> None:
    response = client.post(
        "/v1/admin/redemption-codes",
        json={"kind": "promo", "credits": 100, "reason": "市场活动发码", "confirm": False},
        headers=admin_header(admin),
    )
    assert response.status_code == 422


def test_deactivating_a_code_without_confirmation_is_refused(
    client: TestClient, db: Session, admin: User
) -> None:
    code = redemption.create_code(
        db, kind=RedemptionCodeKind.PROMO, credits=100, actor_user_id=admin.id
    )
    db.commit()

    response = client.post(
        f"/v1/admin/redemption-codes/{code.id}/deactivate",
        json={"reason": "码已泄露，停止使用", "confirm": False},
        headers=admin_header(admin),
    )
    assert response.status_code == 422


def test_admin_can_list_redemption_records_for_a_code(
    client: TestClient, db: Session, admin: User, author: User
) -> None:
    code = redemption.create_code(
        db, kind=RedemptionCodeKind.PROMO, credits=100, max_uses=5, actor_user_id=admin.id
    )
    db.commit()
    redemption.redeem(db, code=code.code, user_id=author.id)
    db.commit()

    response = client.get(
        f"/v1/admin/redemption-codes/{code.id}/records", headers=admin_header(admin)
    )
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["user_id"] == author.id


def test_redemption_endpoints_are_closed_to_anonymous_callers(client: TestClient) -> None:
    assert client.get("/v1/admin/redemption-codes").status_code == 401
