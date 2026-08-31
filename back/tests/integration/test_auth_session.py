"""`POST /v1/auth/logout` must invalidate the refresh token it deletes, not
just tell the browser to forget it — a copy of the cookie taken before
logout (an XSS, a synced device, a shared machine) must stop working
immediately rather than staying valid for up to 14 more days.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.deps import REFRESH_COOKIE_NAME


def _register(client: TestClient, email: str) -> None:
    response = client.post(
        "/v1/auth/register",
        json={
            "email": email,
            "password": "Zaolang2026",
            "display_name": "会话测试",
            "handle": email.split("@")[0].replace("-", "_"),
            "age_confirmed": True,
        },
    )
    assert response.status_code == 201, response.text


def test_refresh_works_before_logout(client: TestClient) -> None:
    _register(client, "session-a@example.com")

    response = client.post("/v1/auth/refresh")
    assert response.status_code == 200, response.text
    assert response.json()["access_token"]


def test_a_refresh_token_captured_before_logout_stops_working_after(
    client: TestClient,
) -> None:
    _register(client, "session-b@example.com")
    leaked_cookie = client.cookies.get(REFRESH_COOKIE_NAME)
    assert leaked_cookie

    logout = client.post("/v1/auth/logout")
    assert logout.status_code == 200

    # The jar already forgot the cookie (that's what `delete_cookie` does
    # locally) — replaying the value captured beforehand is the actual test.
    client.cookies.set(REFRESH_COOKIE_NAME, leaked_cookie)
    replay = client.post("/v1/auth/refresh")
    assert replay.status_code == 401


def test_logout_without_a_session_does_not_error(client: TestClient) -> None:
    response = client.post("/v1/auth/logout")
    assert response.status_code == 200


def test_logout_with_a_garbage_cookie_does_not_error(client: TestClient) -> None:
    client.cookies.set(REFRESH_COOKIE_NAME, "not-a-real-token")
    response = client.post("/v1/auth/logout")
    assert response.status_code == 200
