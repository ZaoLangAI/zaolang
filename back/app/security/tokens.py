"""JWT issuing and verification.

Consumer and back-office sessions are separated by both audience *and* signing
secret. A consumer token presented to `/v1/admin/*` fails signature validation,
so a stolen consumer session can never be escalated by editing a claim.
"""

from __future__ import annotations

import datetime as dt
import secrets
from dataclasses import dataclass
from typing import Any, Literal

import jwt

from app.config import get_settings
from app.domain.errors import AuthRequired

Audience = Literal["consumer", "admin", "refresh"]

CONSUMER_AUDIENCE: Audience = "consumer"
ADMIN_AUDIENCE: Audience = "admin"
REFRESH_AUDIENCE: Audience = "refresh"

ALGORITHM = "HS256"
ISSUER = "zaolang"


@dataclass(frozen=True, slots=True)
class TokenClaims:
    subject: str
    audience: str
    roles: list[str]
    session_id: str
    expires_at: dt.datetime


def _secret_for(audience: Audience) -> str:
    settings = get_settings()
    return settings.admin_jwt_secret if audience == ADMIN_AUDIENCE else settings.jwt_secret


def issue_token(
    *,
    subject: str,
    audience: Audience,
    roles: list[str],
    ttl_seconds: int,
    session_id: str | None = None,
    extra: dict[str, Any] | None = None,
) -> tuple[str, dt.datetime]:
    now = dt.datetime.now(dt.UTC)
    expires_at = now + dt.timedelta(seconds=ttl_seconds)
    payload: dict[str, Any] = {
        "sub": subject,
        "aud": audience,
        "iss": ISSUER,
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
        "roles": roles,
        "sid": session_id or secrets.token_urlsafe(12),
        **(extra or {}),
    }
    token = jwt.encode(payload, _secret_for(audience), algorithm=ALGORITHM)
    return token, expires_at


def decode_token(token: str, *, audience: Audience) -> TokenClaims:
    try:
        payload = jwt.decode(
            token,
            _secret_for(audience),
            algorithms=[ALGORITHM],
            audience=audience,
            issuer=ISSUER,
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthRequired("登录状态已过期，请重新登录。") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthRequired("登录状态无效，请重新登录。") from exc

    return TokenClaims(
        subject=str(payload["sub"]),
        audience=str(payload["aud"]),
        roles=list(payload.get("roles", [])),
        session_id=str(payload.get("sid", "")),
        expires_at=dt.datetime.fromtimestamp(payload["exp"], tz=dt.UTC),
    )


def issue_consumer_tokens(subject: str, roles: list[str]) -> tuple[str, str, dt.datetime]:
    """Access token for the header, refresh token for the httpOnly cookie."""
    settings = get_settings()
    session_id = secrets.token_urlsafe(12)
    access, expires_at = issue_token(
        subject=subject,
        audience=CONSUMER_AUDIENCE,
        roles=roles,
        ttl_seconds=settings.access_token_ttl_seconds,
        session_id=session_id,
    )
    refresh, _ = issue_token(
        subject=subject,
        audience=REFRESH_AUDIENCE,
        roles=roles,
        ttl_seconds=settings.refresh_token_ttl_seconds,
        session_id=session_id,
    )
    return access, refresh, expires_at


def issue_admin_token(subject: str, roles: list[str]) -> tuple[str, dt.datetime]:
    settings = get_settings()
    return issue_token(
        subject=subject,
        audience=ADMIN_AUDIENCE,
        roles=roles,
        ttl_seconds=settings.admin_token_ttl_seconds,
    )
