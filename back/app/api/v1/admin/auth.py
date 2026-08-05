"""Back-office login.

Deliberately separate from `/v1/auth`: a different cookie, a different signing
secret and a shorter lifetime. Signing in to the consumer site never grants a
console session, and signing out of one does not end the other.
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response
from sqlalchemy import select

from app.api import rate_limit
from app.api.deps import ADMIN_COOKIE_NAME, AdminUser, DbSession, client_identity
from app.api.schemas.admin import AdminSessionResponse
from app.api.schemas.auth import AdminLoginRequest
from app.api.schemas.common import OkResponse
from app.config import get_settings
from app.domain.audit import service as audit
from app.domain.errors import AuthRequired, Forbidden
from app.domain.system_log import service as system_log
from app.models import User
from app.models.base import utcnow
from app.models.enums import ADMIN_ROLE_RANK, SystemLogSource
from app.security.passwords import verify_password
from app.security.tokens import issue_admin_token

router = APIRouter(tags=["admin:auth"])


@router.post("/auth/login", response_model=AdminSessionResponse)
def login(
    payload: AdminLoginRequest, request: Request, response: Response, session: DbSession
) -> AdminSessionResponse:
    identity = f"admin:{client_identity(request, None)}"
    rate_limit.enforce("auth_attempt", identity)

    user = session.scalar(select(User).where(User.email == str(payload.email)))
    if user is None or not verify_password(payload.password, user.password_hash):
        system_log.emit(
            source=SystemLogSource.AUTH,
            event="admin_login.failed",
            message=f"{identity} 后台登录失败：邮箱或密码不正确。",
            dedup_key=identity,
            request=request,
        )
        raise AuthRequired("邮箱或密码不正确。")
    if not user.is_active:
        raise AuthRequired("账号不可用。")

    roles = [role for role in user.roles if role in ADMIN_ROLE_RANK]
    if not roles:
        system_log.emit(
            source=SystemLogSource.PERMISSION,
            event="admin_login.forbidden",
            message=f"{identity} 账号 {user.id} 无后台访问权限。",
            dedup_key=identity,
            user_id=user.id,
            request=request,
        )
        # Same wording as a bad password: the response must not reveal that the
        # account exists but lacks console access.
        raise Forbidden("没有后台访问权限。")

    token, expires_at = issue_admin_token(user.id, list(user.roles))
    settings = get_settings()
    response.set_cookie(
        ADMIN_COOKIE_NAME,
        token,
        max_age=settings.admin_token_ttl_seconds,
        httponly=True,
        samesite="strict",
        secure=settings.is_production,
        path="/",
    )
    user.last_login_at = utcnow()
    audit.record(
        session,
        actor=user,
        action="admin.login",
        target_type="user",
        target_id=user.id,
        request=request,
    )
    session.commit()

    return _session_response(user, token, expires_at)


@router.post("/auth/logout", response_model=OkResponse)
def logout(response: Response) -> OkResponse:
    response.delete_cookie(ADMIN_COOKIE_NAME, path="/")
    return OkResponse()


@router.get("/auth/me", response_model=AdminSessionResponse)
def me(user: AdminUser, request: Request) -> AdminSessionResponse:
    """Re-reads the session so the console can render RBAC-aware navigation."""
    token = request.cookies.get(ADMIN_COOKIE_NAME, "")
    _, expires_at = issue_admin_token(user.id, list(user.roles))
    return _session_response(user, token, expires_at)


def _session_response(user: User, token: str, expires_at) -> AdminSessionResponse:  # type: ignore[no-untyped-def]
    roles = [role for role in user.roles if role in ADMIN_ROLE_RANK]
    max_role = max(roles, key=lambda r: ADMIN_ROLE_RANK[r], default="viewer")
    return AdminSessionResponse(
        access_token=token,
        expires_at=expires_at,
        user_id=user.id,
        email=user.email,
        roles=list(user.roles),
        max_role=max_role,
    )
