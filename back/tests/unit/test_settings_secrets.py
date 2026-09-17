"""HMAC signing secrets must meet the HS256 minimum key length."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import Settings


def test_jwt_secrets_reject_keys_shorter_than_32_bytes() -> None:
    with pytest.raises(ValidationError):
        Settings(
            jwt_secret="too-short-for-hs256",
            admin_jwt_secret="x" * 43,
        )
    with pytest.raises(ValidationError):
        Settings(
            jwt_secret="x" * 43,
            admin_jwt_secret="still-too-short",
        )


def test_jwt_secrets_accept_32_byte_keys() -> None:
    settings = Settings(
        jwt_secret="x" * 32,
        admin_jwt_secret="y" * 32,
    )
    assert len(settings.jwt_secret.encode()) == 32
    assert len(settings.admin_jwt_secret.encode()) == 32
