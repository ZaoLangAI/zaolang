"""`PUT /v1/credits/spend-limit` and `POST /v1/generation-jobs/quote:batch`."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.domain.credits import service as credits
from app.models import User
from tests.conftest import auth_header


def test_the_balance_reports_the_cap_the_user_sets_and_clears(
    client: TestClient, db: Session, author: User
) -> None:
    credits.grant(db, author.id, 1_000, idempotency_key=f"grant:{author.id}")

    set_response = client.put(
        "/v1/credits/spend-limit",
        headers=auth_header(author),
        json={"monthly_spend_limit": 300},
    )
    assert set_response.status_code == 200, set_response.text
    assert set_response.json()["monthly_spend_limit"] == 300
    assert set_response.json()["period_remaining"] == 300

    balance = client.get("/v1/credits/balance", headers=auth_header(author)).json()
    assert balance["monthly_spend_limit"] == 300
    assert balance["period_spent"] == 0
    assert len(balance["period"]) == 7

    cleared = client.put(
        "/v1/credits/spend-limit",
        headers=auth_header(author),
        json={"monthly_spend_limit": None},
    )
    assert cleared.json()["monthly_spend_limit"] is None
    assert cleared.json()["period_remaining"] is None


def test_a_zero_or_negative_cap_is_rejected(client: TestClient, author: User) -> None:
    response = client.put(
        "/v1/credits/spend-limit",
        headers=auth_header(author),
        json={"monthly_spend_limit": 0},
    )
    assert response.status_code == 422


def test_a_batch_quote_is_an_exact_sum_checked_against_balance_and_cap(
    client: TestClient, db: Session, author: User
) -> None:
    credits.grant(db, author.id, 1_000, idempotency_key=f"grant:{author.id}")
    body = {
        "items": [
            {
                "operation": "text_to_image",
                "quality_tier": "standard",
                "asset_kind": "scene",
                "count": 3,
            },
            {
                "operation": "text_to_video",
                "quality_tier": "standard",
                "duration_seconds": 5,
                "count": 2,
            },
        ]
    }

    quote = client.post(
        "/v1/generation-jobs/quote:batch", headers=auth_header(author), json=body
    ).json()
    lines = quote["items"]
    assert [line["count"] for line in lines] == [3, 2]
    assert all(line["credits"] == line["unit_credits"] * line["count"] for line in lines)
    assert quote["total_credits"] == sum(line["credits"] for line in lines)
    assert quote["period_remaining"] is None
    assert quote["within_spend_limit"] is True

    credits.set_monthly_spend_limit(db, author.id, 1)
    capped = client.post(
        "/v1/generation-jobs/quote:batch", headers=auth_header(author), json=body
    ).json()
    assert capped["period_remaining"] == 1
    assert capped["within_spend_limit"] is False
    assert capped["sufficient"] is False
