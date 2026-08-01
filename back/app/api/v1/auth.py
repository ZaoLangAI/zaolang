"""Authentication, session and preferences."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api import rate_limit
from app.api.deps import (
    REFRESH_COOKIE_NAME,
    CurrentUser,
    DbSession,
    client_identity,
)
from app.api.schemas.auth import (
    LoginRequest,
    MeResponse,
    PreferencesRequest,
    ProfileResponse,
    ProfileUpdateRequest,
    RegisterRequest,
    TokenResponse,
)
from app.api.schemas.common import OkResponse
from app.config import get_settings
from app.domain.credits import service as credits_service
from app.domain.errors import AuthRequired, Conflict, ValidationFailed
from app.models import Profile, User
from app.models.base import utcnow
from app.models.enums import UserRole
from app.platform_config import service as config_service
from app.security.passwords import hash_password, needs_rehash, verify_password
from app.security.tokens import REFRESH_AUDIENCE, decode_token, issue_consumer_tokens

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse, status_code=201)
def register(
    payload: RegisterRequest, request: Request, response: Response, session: DbSession
) -> TokenResponse:
    rate_limit.enforce("auth_attempt", client_identity(request, None))

    if not config_service.is_enabled(session, "public_registration"):
        raise Conflict("当前未开放注册。")
    if not payload.age_confirmed:
        raise ValidationFailed("需要确认已满 18 周岁。", fields={"age_confirmed": "必须勾选"})

    if session.scalar(select(User).where(User.email == str(payload.email))):
        raise Conflict("该邮箱已注册。")
    if session.scalar(select(Profile).where(Profile.handle == payload.handle)):
        raise Conflict("该用户名已被占用。")

    user = User(
        email=str(payload.email),
        password_hash=hash_password(payload.password),
        region=payload.region,
        locale=payload.locale,
        roles=[UserRole.USER.value],
        age_gate_confirmed_at=utcnow(),
    )
    session.add(user)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise Conflict("该邮箱已注册。") from exc

    session.add(Profile(user_id=user.id, display_name=payload.display_name, handle=payload.handle))
    # A starter grant lets a new user try preview-tier generation immediately.
    credits_service.grant(
        session,
        user.id,
        credits_service.SIGNUP_GRANT_CREDITS,
        idempotency_key=f"signup:{user.id}",
    )
    session.commit()

    return _issue_session(user, response)


@router.post("/login", response_model=TokenResponse)
def login(
    payload: LoginRequest, request: Request, response: Response, session: DbSession
) -> TokenResponse:
    rate_limit.enforce("auth_attempt", client_identity(request, None))

    user = session.scalar(select(User).where(User.email == str(payload.email)))
    # The same message for both branches so the endpoint cannot be used to
    # enumerate registered addresses.
    if user is None or not verify_password(payload.password, user.password_hash):
        raise AuthRequired("邮箱或密码不正确。")
    if not user.is_active:
        raise AuthRequired("账号不可用，请联系支持。")

    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(payload.password)
    user.last_login_at = utcnow()
    session.commit()

    return _issue_session(user, response)


@router.post("/refresh", response_model=TokenResponse)
def refresh(request: Request, response: Response, session: DbSession) -> TokenResponse:
    """Exchanges the httpOnly refresh cookie for a new access token."""
    cookie = request.cookies.get(REFRESH_COOKIE_NAME)
    if not cookie:
        raise AuthRequired("登录状态已失效，请重新登录。")

    claims = decode_token(cookie, audience=REFRESH_AUDIENCE)
    user = session.get(User, claims.subject)
    if user is None or not user.is_active:
        raise AuthRequired("登录状态已失效，请重新登录。")
    return _issue_session(user, response)


@router.post("/logout", response_model=OkResponse)
def logout(response: Response) -> OkResponse:
    response.delete_cookie(REFRESH_COOKIE_NAME, path="/")
    return OkResponse()


@router.get("/me", response_model=MeResponse)
def me(user: CurrentUser, session: DbSession) -> MeResponse:
    profile = session.scalar(select(Profile).where(Profile.user_id == user.id))
    account = credits_service.get_or_create_account(session, user.id)
    session.commit()
    return MeResponse(
        id=user.id,
        email=user.email,
        roles=list(user.roles),
        status=user.status,
        region=user.region,
        locale=user.locale,
        theme=user.theme,
        age_gate_confirmed=user.age_gate_confirmed_at is not None,
        profile=ProfileResponse.model_validate(profile) if profile else None,
        available_credits=account.available_balance,
        reserved_credits=account.reserved_balance,
    )


@router.patch("/me/preferences", response_model=MeResponse)
def update_preferences(
    payload: PreferencesRequest, user: CurrentUser, session: DbSession
) -> MeResponse:
    """Region, locale and theme in one call.

    Theme lives here rather than only in a cookie so the choice follows the
    user across devices.
    """
    if payload.region is not None:
        user.region = payload.region
    if payload.locale is not None:
        user.locale = payload.locale
    if payload.theme is not None:
        user.theme = payload.theme

    profile = session.scalar(select(Profile).where(Profile.user_id == user.id))
    if profile is not None:
        if payload.reduce_motion is not None:
            profile.reduce_motion = payload.reduce_motion
        if payload.notify_on_remix is not None:
            profile.notify_on_remix = payload.notify_on_remix
    session.commit()
    return me(user, session)


@router.patch("/me/profile", response_model=ProfileResponse)
def update_profile(
    payload: ProfileUpdateRequest, user: CurrentUser, session: DbSession
) -> ProfileResponse:
    profile = session.scalar(select(Profile).where(Profile.user_id == user.id))
    if profile is None:
        raise Conflict("资料不存在。")

    for field in ("display_name", "bio", "location", "avatar_asset_id", "cover_asset_id"):
        value = getattr(payload, field)
        if value is not None:
            setattr(profile, field, value)
    if payload.public_profile is not None:
        profile.public_profile = payload.public_profile
    session.commit()
    return ProfileResponse.model_validate(profile)


def _issue_session(user: User, response: Response) -> TokenResponse:
    settings = get_settings()
    access, refresh_token, expires_at = issue_consumer_tokens(user.id, list(user.roles))
    response.set_cookie(
        REFRESH_COOKIE_NAME,
        refresh_token,
        max_age=settings.refresh_token_ttl_seconds,
        httponly=True,
        samesite="lax",
        secure=settings.is_production,
        path="/",
    )
    return TokenResponse(access_token=access, expires_at=expires_at)
