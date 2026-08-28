"""Short-video delivery spec catalogue.

`app.domain.shortform.service` also owns publication-intent bookkeeping
(`create_publication_intent`/`list_publication_intents`/`mark_submitted`/
`mark_failed`), but that is only ever reached through
`app.domain.distribution.service.publish_fanout` now — see
`tests/integration/test_distribution.py` for coverage of that path. The
standalone `/v1/works/{id}/publications` routes that used to call it directly
were removed with the old single-clip `ShortformStudio`.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.api import rate_limit
from app.models import User
from tests.conftest import auth_header

# --- GET /v1/shortform/profiles -----------------------------------------


def test_the_spec_catalogue_is_readable_without_signing_in(client: TestClient) -> None:
    """Delivery-variant exports (`zaolang-editor-drama`) render their
    profile picker from this before asking anyone to log in."""
    response = client.get("/v1/shortform/profiles")

    assert response.status_code == 200
    body = response.json()
    assert body["default_profile"] == "douyin_vertical"
    keys = {profile["key"] for profile in body["profiles"]}
    assert {"douyin_vertical", "douyin_landscape"} <= keys


def test_the_catalogue_carries_the_limits_the_client_validates_against(
    client: TestClient,
) -> None:
    body = client.get("/v1/shortform/profiles").json()
    vertical = next(p for p in body["profiles"] if p["key"] == "douyin_vertical")

    assert vertical["aspect_ratio"] == "9:16"
    assert vertical["max_duration_seconds"] <= 30
    assert vertical["max_title_length"] > 0
    assert vertical["require_ai_disclosure"] is True


def test_reading_the_catalogue_is_rate_limited(client: TestClient, author: User) -> None:
    identity = f"user:{author.id}"
    for _ in range(rate_limit.RULES["public_read"].limit):
        rate_limit.enforce("public_read", identity)

    response = client.get("/v1/shortform/profiles", headers=auth_header(author))

    assert response.status_code == 429
    assert response.headers.get("retry-after")
