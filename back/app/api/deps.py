"""FastAPI dependencies: sessions, identity, RBAC and rate-limit buckets."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Header, Request
from sqlalchemy.orm import Session

from app.api import rate_limit
from app.db import get_db
from app.domain.errors import AgeGateRequired, AuthRequired, Forbidden
from app.models import User
from app.models.enums import ADMIN_ROLE_RANK, UserStatus
from app.observability.context import set_user_id
from app.security.tokens import ADMIN_AUDIENCE, CONSUMER_AUDIENCE, decode_token

DbSession = Annotated[Session, Depends(get_db)]

ADMIN_COOKIE_NAME = "zl_admin_session"
REFRESH_COOKIE_NAME = "zl_refresh"


def _bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return token.strip()


def _load_active_user(session: Session, user_id: str) -> User:
    user = session.get(User, user_id)
    if user is None or user.status == UserStatus.DELETED:
        raise AuthRequired("账号不存在或已注销。")
    if user.status == UserStatus.SUSPENDED:
        raise Forbidden("账号已被封禁。", reason=user.suspended_reason or "")
    return user


def get_current_user(
    session: DbSession,
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    token = _bearer_token(authorization)
    if token is None:
        raise AuthRequired()
    claims = decode_token(token, audience=CONSUMER_AUDIENCE)
    user = _load_active_user(session, claims.subject)
    set_user_id(user.id)
    return user


def get_optional_user(
    session: DbSession,
    authorization: Annotated[str | None, Header()] = None,
) -> User | None:
    """Identity for endpoints that behave differently when signed in.

    A malformed or expired token is treated as anonymous rather than an error,
    so a stale tab still renders public content.
    """
    token = _bearer_token(authorization)
    if token is None:
        return None
    try:
        claims = decode_token(token, audience=CONSUMER_AUDIENCE)
        user = _load_active_user(session, claims.subject)
    except (AuthRequired, Forbidden):
        return None
    set_user_id(user.id)
    return user


def require_age_gate(user: Annotated[User, Depends(get_current_user)]) -> User:
    if user.age_gate_confirmed_at is None:
        raise AgeGateRequired()
    return user


def get_admin_user(
    request: Request,
    session: DbSession,
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    """Back-office identity.

    The token must be signed with the admin secret and carry the admin
    audience, so a consumer session can never reach `/v1/admin/*`.
    """
    token = _bearer_token(authorization) or request.cookies.get(ADMIN_COOKIE_NAME)
    if not token:
        raise AuthRequired("请先登录后台。")
    claims = decode_token(token, audience=ADMIN_AUDIENCE)
    user = _load_active_user(session, claims.subject)
    if not any(role in ADMIN_ROLE_RANK for role in user.roles):
        raise Forbidden("没有后台访问权限。")
    set_user_id(user.id)
    request.state.admin_user = user
    return user


def require_admin_role(minimum: str):  # type: ignore[no-untyped-def]
    """Enforces a minimum back-office rank.

    Roles are ranked, so `operator` automatically satisfies a `reviewer`
    requirement without listing every role at every endpoint.
    """
    required_rank = ADMIN_ROLE_RANK[minimum]

    def _dependency(user: Annotated[User, Depends(get_admin_user)]) -> User:
        actual = max((ADMIN_ROLE_RANK.get(role, 0) for role in user.roles), default=0)
        if actual < required_rank:
            raise Forbidden(f"该操作需要 {minimum} 及以上权限。")
        return user

    return _dependency


def client_identity(request: Request, user: User | None) -> str:
    if user is not None:
        return f"user:{user.id}"
    forwarded = request.headers.get("x-forwarded-for", "")
    ip = (
        forwarded.split(",")[0].strip()
        if forwarded
        else (request.client.host if request.client else "unknown")
    )
    return f"ip:{ip}"


def rate_limited(bucket: str):  # type: ignore[no-untyped-def]
    def _dependency(
        request: Request,
        user: Annotated[User | None, Depends(get_optional_user)] = None,
    ) -> None:
        rate_limit.enforce(bucket, client_identity(request, user))

    return _dependency


def get_idempotency_key(
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> str | None:
    return idempotency_key


def db_transaction(session: DbSession) -> Iterator[Session]:
    """Wraps a handler in one transaction, committing only on success."""
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise


CurrentUser = Annotated[User, Depends(get_current_user)]
OptionalUser = Annotated[User | None, Depends(get_optional_user)]
AdminUser = Annotated[User, Depends(get_admin_user)]
IdempotencyKey = Annotated[str | None, Depends(get_idempotency_key)]
