"""Authentication and profile payloads."""

from __future__ import annotations

import datetime as dt

from pydantic import EmailStr, Field, field_validator

from app.api.schemas.common import ApiModel
from app.models.enums import Locale, Region, ThemePreference
from app.security.passwords import MIN_PASSWORD_LENGTH


class RegisterRequest(ApiModel):
    email: EmailStr
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=128)
    display_name: str = Field(min_length=1, max_length=80)
    handle: str = Field(min_length=3, max_length=40, pattern=r"^[a-z0-9_]+$")
    region: Region = Region.CN
    locale: Locale = Locale.ZH_CN
    # The platform is 18+; registration cannot proceed without an explicit
    # confirmation, and the timestamp is what the compliance record relies on.
    age_confirmed: bool = False

    @field_validator("password")
    @classmethod
    def _password_strength(cls, value: str) -> str:
        if value.isalpha() or value.isdigit():
            raise ValueError("密码需要同时包含字母与数字。")
        return value


class LoginRequest(ApiModel):
    email: EmailStr
    password: str


class AdminLoginRequest(ApiModel):
    email: EmailStr
    password: str


class TokenResponse(ApiModel):
    access_token: str
    token_type: str = "Bearer"
    expires_at: dt.datetime


class ProfileResponse(ApiModel):
    display_name: str
    handle: str
    bio: str | None = None
    location: str | None = None
    avatar_asset_id: str | None = None
    cover_asset_id: str | None = None
    public_profile: bool = True
    notify_on_remix: bool = True
    reduce_motion: bool = False


class MeResponse(ApiModel):
    id: str
    email: EmailStr
    roles: list[str]
    status: str
    region: Region
    locale: Locale
    theme: ThemePreference
    age_gate_confirmed: bool
    profile: ProfileResponse | None = None
    available_credits: int = 0
    reserved_credits: int = 0


class PreferencesRequest(ApiModel):
    """Partial update; every field is optional."""

    region: Region | None = None
    locale: Locale | None = None
    theme: ThemePreference | None = None
    reduce_motion: bool | None = None
    notify_on_remix: bool | None = None


class PublicProfileResponse(ApiModel):
    user_id: str
    handle: str
    display_name: str
    bio: str | None = None
    location: str | None = None
    avatar_url: str | None = None
    cover_url: str | None = None
    work_count: int = 0
    follower_count: int = 0
    following_count: int = 0
    viewer_following: bool = False
    is_self: bool = False


class ProfileUpdateRequest(ApiModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=80)
    bio: str | None = Field(default=None, max_length=500)
    location: str | None = Field(default=None, max_length=80)
    avatar_asset_id: str | None = None
    cover_asset_id: str | None = None
    public_profile: bool | None = None
