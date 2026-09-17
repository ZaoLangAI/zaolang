"""Project-scoped MCP access tokens. Independent of consumer/admin audiences."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

import jwt
from sqlalchemy.orm import Session

from app.config import get_settings
from app.domain.editor import flags as editor_flags
from app.domain.editor import service as editor_service
from app.domain.errors import AuthRequired, ProjectForbidden, ScopeRequired, ValidationFailed
from app.models import McpTokenGrant
from app.models.base import new_id, utcnow

MCP_AUDIENCE = "mcp"
MCP_ISSUER = "zaolang-mcp"
ALLOWED_SCOPES = frozenset({"drama:read", "editor:read", "editor:write", "editor:export"})
ALGORITHM = "HS256"


@dataclass(frozen=True, slots=True)
class McpPrincipal:
    user_id: str
    series_id: str
    grant_id: str
    client_id: str
    scopes: frozenset[str]
    jti: str


def issue_grant(
    session: Session,
    *,
    user_id: str,
    series_id: str,
    client_id: str,
    scopes: list[str],
    ttl_seconds: int = 60 * 60 * 8,
) -> tuple[McpTokenGrant, str, dt.datetime]:
    editor_flags.require_flag(session, editor_flags.FLAG_MCP, user_id=user_id)
    editor_service.require_drama_series(session, user_id=user_id, series_id=series_id)
    normalised = sorted({scope.strip() for scope in scopes if scope.strip()})
    if not normalised or any(scope not in ALLOWED_SCOPES for scope in normalised):
        raise ValidationFailed("MCP 权限范围不合法。")
    now = utcnow()
    expires_at = now + dt.timedelta(seconds=ttl_seconds)
    jti = new_id("jti")
    grant = McpTokenGrant(
        user_id=user_id,
        series_id=series_id,
        client_id=client_id.strip()[:80],
        jti=jti,
        scopes_json=normalised,
        expires_at=expires_at,
    )
    session.add(grant)
    session.flush()
    settings = get_settings()
    payload: dict[str, Any] = {
        "sub": user_id,
        "aud": MCP_AUDIENCE,
        "iss": MCP_ISSUER,
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
        "jti": jti,
        "project_id": series_id,
        "grant_id": grant.id,
        "client_id": grant.client_id,
        "scopes": normalised,
    }
    token = jwt.encode(payload, settings.mcp_jwt_secret, algorithm=ALGORITHM)
    return grant, token, expires_at


def revoke_grant(session: Session, *, user_id: str, grant_id: str) -> None:
    grant = session.get(McpTokenGrant, grant_id)
    if grant is None or grant.user_id != user_id:
        raise ValidationFailed("授权不存在。")
    grant.revoked_at = utcnow()
    session.flush()


def decode_mcp_token(session: Session, token: str) -> McpPrincipal:
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.mcp_jwt_secret,
            algorithms=[ALGORITHM],
            audience=MCP_AUDIENCE,
            issuer=MCP_ISSUER,
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthRequired("MCP 令牌已过期。") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthRequired("MCP 令牌无效。") from exc
    grant = session.get(McpTokenGrant, str(payload.get("grant_id") or ""))
    if grant is None or grant.revoked_at is not None or grant.jti != payload.get("jti"):
        raise AuthRequired("MCP 授权已撤销。")
    if grant.expires_at <= utcnow():
        raise AuthRequired("MCP 令牌已过期。")
    scopes = frozenset(str(item) for item in (payload.get("scopes") or []))
    return McpPrincipal(
        user_id=str(payload["sub"]),
        series_id=str(payload["project_id"]),
        grant_id=grant.id,
        client_id=str(payload.get("client_id") or grant.client_id),
        scopes=scopes,
        jti=grant.jti,
    )


def require_scope(principal: McpPrincipal, scope: str) -> None:
    if scope not in principal.scopes:
        raise ScopeRequired()


def require_project(principal: McpPrincipal, project_id: str) -> None:
    if project_id != principal.series_id:
        raise ProjectForbidden()
