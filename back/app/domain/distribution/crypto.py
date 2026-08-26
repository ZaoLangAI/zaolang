"""Fernet encryption for platform OAuth tokens at rest.

`settings.platform_token_encryption_key` is empty by default (no platform
credentials exist yet), which must not crash anything at import time — the
same convention `app.storage.backends.tencent_cos` follows for its own
"not configured" fields. It only becomes an error the moment someone actually
tries to encrypt or decrypt a token, which is exactly when it matters.

Tokens are never logged: nothing in this module (or any caller) may put a raw
access/refresh token into a log line or a `DomainError` detail.
"""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings
from app.domain.errors import PlatformNotConfigured, PlatformOAuthFailed


def _fernet() -> Fernet:
    key = get_settings().platform_token_encryption_key
    if not key:
        raise PlatformNotConfigured("尚未配置平台 Token 加密密钥。")
    try:
        return Fernet(key.encode("utf-8"))
    except (ValueError, TypeError) as exc:
        # Wrong length / not valid url-safe base64 — a misconfigured key is
        # indistinguishable from "not set up" from the caller's point of view.
        raise PlatformNotConfigured("平台 Token 加密密钥配置不正确。") from exc


def encrypt_token(plaintext: str) -> str:
    """Raises `PlatformNotConfigured` if the encryption key is empty/invalid."""
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_token(ciphertext: str) -> str:
    """Raises `PlatformOAuthFailed` if the stored value is corrupted or was
    encrypted under a different key — never leaks the ciphertext or key."""
    try:
        return _fernet().decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise PlatformOAuthFailed("平台授权信息已损坏，请重新连接账号。") from exc
