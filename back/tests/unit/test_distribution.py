"""Platform-distribution clients and OAuth-state signing.

Local/test `Settings` leaves every Douyin/Kuaishou app key empty by default
(no org has finished platform registration yet) — that default state is
exactly what these tests exercise, no monkeypatching needed to get there.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.domain.distribution import crypto, service
from app.domain.distribution.douyin_client import DouyinClient
from app.domain.distribution.kuaishou_client import KuaishouClient
from app.domain.errors import PlatformNotConfigured, PlatformOAuthFailed


@pytest.mark.parametrize("client", [DouyinClient(), KuaishouClient()])
def test_authorize_url_raises_when_not_configured(client) -> None:
    with patch("httpx.Client") as mock_client:
        with pytest.raises(PlatformNotConfigured):
            client.authorize_url("state")
        mock_client.assert_not_called()


@pytest.mark.parametrize("client", [DouyinClient(), KuaishouClient()])
def test_exchange_code_raises_when_not_configured(client) -> None:
    with patch("httpx.Client") as mock_client:
        with pytest.raises(PlatformNotConfigured):
            client.exchange_code("code")
        mock_client.assert_not_called()


@pytest.mark.parametrize("client", [DouyinClient(), KuaishouClient()])
def test_init_upload_raises_when_not_configured(client) -> None:
    with patch("httpx.Client") as mock_client:
        with pytest.raises(PlatformNotConfigured):
            client.init_upload("token")
        mock_client.assert_not_called()


def test_encrypt_token_raises_when_key_not_configured() -> None:
    with pytest.raises(PlatformNotConfigured):
        crypto.encrypt_token("secret")


def test_encrypt_decrypt_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    from cryptography.fernet import Fernet

    from app import config as config_module

    key = Fernet.generate_key().decode()
    settings = config_module.get_settings()
    monkeypatch.setattr(settings, "platform_token_encryption_key", key)

    ciphertext = crypto.encrypt_token("my-access-token")
    assert ciphertext != "my-access-token"
    assert crypto.decrypt_token(ciphertext) == "my-access-token"


def test_decrypt_token_rejects_corrupted_ciphertext(monkeypatch: pytest.MonkeyPatch) -> None:
    from cryptography.fernet import Fernet

    from app import config as config_module

    key = Fernet.generate_key().decode()
    settings = config_module.get_settings()
    monkeypatch.setattr(settings, "platform_token_encryption_key", key)

    with pytest.raises(PlatformOAuthFailed):
        crypto.decrypt_token("not-a-real-token")


def test_state_round_trips() -> None:
    state = service._sign_state(user_id="user_abc", channel="douyin")
    user_id = service._verify_state(state, expected_channel="douyin")
    assert user_id == "user_abc"


def test_state_rejects_tampered_signature() -> None:
    state = service._sign_state(user_id="user_abc", channel="douyin")
    payload_b64, _signature = state.split(".", 1)
    tampered = f"{payload_b64}.deadbeef"
    with pytest.raises(PlatformOAuthFailed):
        service._verify_state(tampered, expected_channel="douyin")


def test_state_rejects_channel_mismatch() -> None:
    state = service._sign_state(user_id="user_abc", channel="douyin")
    with pytest.raises(PlatformOAuthFailed):
        service._verify_state(state, expected_channel="kuaishou")


def test_state_rejects_stale_timestamp() -> None:
    with patch("time.time", return_value=1_000_000.0):
        state = service._sign_state(user_id="user_abc", channel="douyin")
    with patch("time.time", return_value=1_000_000.0 + service.STATE_TTL_SECONDS + 1):
        with pytest.raises(PlatformOAuthFailed):
            service._verify_state(state, expected_channel="douyin")


def test_config_status_is_false_by_default() -> None:
    assert service.config_status() == {"douyin": False, "kuaishou": False}
