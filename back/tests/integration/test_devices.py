"""`/v1/me/devices`: the APNs token registry push fan-out reads from."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.notifications import push
from app.models import Device, User
from tests.conftest import auth_header

TOKEN = "apns-token-0001"


def _register(client: TestClient, user: User, token: str = TOKEN, **extra: Any) -> Any:
    return client.post(
        "/v1/me/devices",
        json={"push_token": token, "locale": "zh-CN", **extra},
        headers=auth_header(user),
    )


def test_registering_a_device_stores_the_token(
    client: TestClient, db: Session, author: User
) -> None:
    response = _register(client, author)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["platform"] == "ios"
    assert body["locale"] == "zh-CN"

    device = db.get(Device, body["id"])
    assert device is not None
    assert device.user_id == author.id
    assert device.push_token == TOKEN


def test_anonymous_callers_cannot_register(client: TestClient) -> None:
    response = client.post("/v1/me/devices", json={"push_token": TOKEN, "locale": "zh-CN"})
    assert response.status_code == 401


def test_a_too_short_token_is_rejected(client: TestClient, author: User) -> None:
    assert _register(client, author, token="short").status_code == 422


def test_re_registering_a_token_updates_the_same_row(
    client: TestClient, db: Session, author: User
) -> None:
    first = _register(client, author).json()
    second = _register(client, author, locale="en-US").json()

    assert second["id"] == first["id"]
    assert second["locale"] == "en-US"
    assert len(list(db.scalars(select(Device).where(Device.push_token == TOKEN)))) == 1


def test_a_token_moves_to_whoever_registers_it_last(
    client: TestClient, db: Session, author: User, remixer: User
) -> None:
    """One phone, two accounts: pushes must follow the signed-in account, not
    the one that happened to register the token first."""
    device_id = _register(client, author).json()["id"]
    assert _register(client, remixer).json()["id"] == device_id

    device = db.get(Device, device_id)
    assert device is not None
    db.refresh(device)
    assert device.user_id == remixer.id


def test_only_the_owner_can_remove_a_device(
    client: TestClient, db: Session, author: User, remixer: User
) -> None:
    device_id = _register(client, author).json()["id"]

    assert (
        client.delete(f"/v1/me/devices/{device_id}", headers=auth_header(remixer)).status_code
        == 403
    )
    assert db.get(Device, device_id) is not None

    assert (
        client.delete(f"/v1/me/devices/{device_id}", headers=auth_header(author)).status_code == 200
    )
    assert db.get(Device, device_id) is None
    assert (
        client.delete(f"/v1/me/devices/{device_id}", headers=auth_header(author)).status_code == 404
    )


def test_a_notification_pushes_to_every_registered_device(
    client: TestClient, author: User, remixer: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(
        push,
        "send_push",
        lambda token, *, title_key, payload: sent.append((token, title_key)),
    )
    _register(client, author, token="apns-phone-0001")
    _register(client, author, token="apns-tablet-0001", platform="ipados")

    client.post(f"/v1/users/{author.id}/follow", headers=auth_header(remixer))

    assert sorted(sent) == [
        ("apns-phone-0001", "notification.new_follower"),
        ("apns-tablet-0001", "notification.new_follower"),
    ]
