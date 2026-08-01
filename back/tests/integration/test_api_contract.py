"""Consumer API contract: auth, discovery, error envelope and ownership."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import User
from app.models.enums import Visibility
from tests.conftest import auth_header
from tests.factories import make_work


def test_register_returns_a_session_and_a_starter_grant(client: TestClient) -> None:
    response = client.post(
        "/v1/auth/register",
        json={
            "email": "newcomer@example.com",
            "password": "Zaolang2026",
            "display_name": "新来的",
            "handle": "newcomer",
            "age_confirmed": True,
        },
    )
    assert response.status_code == 201
    token = response.json()["access_token"]

    me = client.get("/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["available_credits"] > 0


def test_registration_refuses_an_unconfirmed_age_gate(client: TestClient) -> None:
    response = client.post(
        "/v1/auth/register",
        json={
            "email": "minor@example.com",
            "password": "Zaolang2026",
            "display_name": "未确认",
            "handle": "unconfirmed",
            "age_confirmed": False,
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"


def test_login_does_not_distinguish_unknown_email_from_wrong_password(
    client: TestClient, author: User
) -> None:
    unknown = client.post(
        "/v1/auth/login", json={"email": "nobody@example.com", "password": "Zaolang2026"}
    )
    wrong = client.post(
        "/v1/auth/login", json={"email": author.email, "password": "WrongPassword1"}
    )
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json()["error"]["message"] == wrong.json()["error"]["message"]


def test_every_error_carries_a_request_id(client: TestClient) -> None:
    response = client.get("/v1/works/wrk_does_not_exist")
    assert response.status_code == 404
    body = response.json()["error"]
    assert body["code"] == "NOT_FOUND"
    assert body["request_id"] == response.headers["x-request-id"]


def test_a_private_work_is_indistinguishable_from_a_missing_one(
    client: TestClient, db: Session, author: User, remixer: User
) -> None:
    work, _ = make_work(db, author, visibility=Visibility.PRIVATE)
    db.commit()

    response = client.get(f"/v1/works/{work.id}", headers=auth_header(remixer))
    assert response.status_code == 404


def test_discovery_lists_only_public_active_works(
    client: TestClient, db: Session, author: User
) -> None:
    public, _ = make_work(db, author, title="公开作品")
    private, _ = make_work(db, author, title="私密作品", visibility=Visibility.PRIVATE)
    db.commit()

    ids = {item["id"] for item in client.get("/v1/works").json()["items"]}
    assert public.id in ids
    assert private.id not in ids


def test_liking_is_idempotent(client: TestClient, db: Session, author: User, remixer: User) -> None:
    work, _ = make_work(db, author)
    db.commit()

    first = client.post(f"/v1/works/{work.id}/like", headers=auth_header(remixer))
    second = client.post(f"/v1/works/{work.id}/like", headers=auth_header(remixer))
    assert first.json()["count"] == second.json()["count"] == 1


def test_a_protected_endpoint_rejects_an_anonymous_caller(client: TestClient) -> None:
    response = client.get("/v1/credits/balance")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"


def test_visibility_cannot_be_changed_by_a_non_owner(
    client: TestClient, db: Session, author: User, remixer: User
) -> None:
    work, _ = make_work(db, author)
    db.commit()

    response = client.patch(
        f"/v1/works/{work.id}/visibility",
        json={"visibility": Visibility.PRIVATE.value},
        headers=auth_header(remixer),
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_a_view_only_work_hides_its_reusable_parameters(
    client: TestClient, db: Session, author: User, remixer: User
) -> None:
    """The licence is meaningless if the prompt ships with a view-only work."""
    work, _ = make_work(db, author, visibility=Visibility.PUBLIC_VIEW_ONLY)
    db.commit()

    body = client.get(f"/v1/works/{work.id}", headers=auth_header(remixer)).json()
    assert body["can_remix"] is False
    assert body["reusable_params"] is None


def test_a_remixable_work_exposes_its_parameters(
    client: TestClient, db: Session, author: User, remixer: User
) -> None:
    work, _ = make_work(db, author, visibility=Visibility.PUBLIC_REMIXABLE)
    db.commit()

    body = client.get(f"/v1/works/{work.id}", headers=auth_header(remixer)).json()
    assert body["can_remix"] is True
    assert body["reusable_params"]["seed"] == 42


def test_quote_is_returned_before_any_credits_move(
    client: TestClient, db: Session, author: User
) -> None:
    before = client.get("/v1/credits/balance", headers=auth_header(author)).json()
    quote = client.post(
        "/v1/generation-jobs/quote",
        json={"operation": "text_to_image", "quality_tier": "standard"},
        headers=auth_header(author),
    )
    after = client.get("/v1/credits/balance", headers=auth_header(author)).json()

    assert quote.status_code == 200
    assert quote.json()["credits"] > 0
    assert before["available"] == after["available"]
