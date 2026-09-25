"""Application settings.

Secrets are only ever read from the environment. Nothing in this module may be
logged, echoed through the config centre, or placed into an agent prompt.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# The literal default values below, in one place so the startup guard
# (`Settings._reject_default_secrets_in_production`) can check every signing
# secret against exactly what a fresh checkout ships without duplicating the
# strings themselves.
_DEFAULT_JWT_SECRET = "dev-only-change-me-jwt-secret-please-rotate"
_DEFAULT_ADMIN_JWT_SECRET = "dev-only-change-me-admin-jwt-secret-rotate"
_DEFAULT_MCP_JWT_SECRET = "dev-only-change-me-mcp-jwt-secret-please-rotate"
_DEFAULT_PAYMENT_WEBHOOK_SECRET = "dev-only-change-me-webhook"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    app_env: Literal["local", "test", "ci", "production"] = "local"
    app_version: str = "0.0.0-dev"
    api_base_url: str = "http://localhost:3001"
    web_base_url: str = "http://localhost:3000"

    database_url: str = "postgresql+psycopg://zaolang:zaolang@localhost:5433/zaolang"
    test_database_url: str = "postgresql+psycopg://zaolang:zaolang@localhost:5433/zaolang_test"
    redis_url: str = "redis://localhost:6380/0"

    # HS256 requires >= 32 bytes (RFC 7518 §3.2 / PyJWT). Local defaults are
    # random placeholders only — rotate before any shared or production
    # deploy. `_reject_default_secrets_in_production` below refuses to even
    # start the process if `app_env == "production"` and any of these four
    # still match what a fresh checkout ships — `is_production` elsewhere
    # only gates a handful of routes (the seed endpoint, admin data export),
    # it does not stop the process from booting with a guessable secret.
    jwt_secret: str = _DEFAULT_JWT_SECRET
    admin_jwt_secret: str = _DEFAULT_ADMIN_JWT_SECRET
    mcp_jwt_secret: str = _DEFAULT_MCP_JWT_SECRET
    payment_webhook_secret: str = _DEFAULT_PAYMENT_WEBHOOK_SECRET
    access_token_ttl_seconds: int = 60 * 30
    refresh_token_ttl_seconds: int = 60 * 60 * 24 * 14
    admin_token_ttl_seconds: int = 60 * 60 * 8

    # Which object storage backend is active. MinIO is the local/dev default;
    # `tencent_cos` is selected purely by config, no code change, for a
    # deployment that wants managed storage instead of self-hosted MinIO.
    storage_backend: Literal["minio", "tencent_cos"] = "minio"

    s3_endpoint_url: str = "http://localhost:9000"
    s3_public_endpoint_url: str = "http://localhost:9000"
    s3_region: str = "us-east-1"
    s3_bucket: str = "zaolang-media"
    s3_access_key: str = "zaolang"
    s3_secret_key: str = "zaolang-secret"

    # Tencent COS — only read when storage_backend == "tencent_cos".
    cos_secret_id: str = ""
    cos_secret_key: str = ""
    cos_region: str = "ap-guangzhou"
    cos_bucket: str = ""  # COS bucket names carry a -<APPID> suffix
    # Public/CDN domain for presigned URLs, if different from the region
    # endpoint `cos_region` derives. Plays the same role `s3_public_endpoint_url`
    # plays for MinIO — see `embed_reference_images_as_base64`.
    cos_public_endpoint_url: str = ""

    upload_url_ttl_seconds: int = 60 * 10
    download_url_ttl_seconds: int = 60 * 15

    # Fernet key (32 url-safe base64-encoded bytes) used to encrypt platform
    # OAuth tokens at rest. Empty means "not configured yet" — the same
    # convention as the COS fields above — validated lazily in
    # `app.domain.distribution.crypto`, not at import time.
    platform_token_encryption_key: str = ""

    # Douyin (抖音) Open Platform app credentials. Empty = that org's platform
    # registration is not done yet; every `DouyinClient` method must raise
    # `PlatformNotConfigured` rather than attempt a real call.
    douyin_app_key: str = ""
    douyin_app_secret: str = ""
    douyin_redirect_uri: str = ""

    # Kuaishou (快手) Open Platform app credentials — same empty-means-
    # unconfigured convention as the Douyin fields above.
    kuaishou_app_id: str = ""
    kuaishou_app_secret: str = ""
    kuaishou_redirect_uri: str = ""

    @property
    def embed_reference_images_as_base64(self) -> bool:
        """Whether a provider reference image must be inlined as base64
        rather than handed over as a presigned URL from the active backend.

        `local`/`test` both default the MinIO `s3_public_endpoint_url` to
        `http://localhost:9000` — reachable from this machine's own browser,
        never from a real external provider's servers (aihubmix, an HTTP
        API on the public internet). A presigned URL there is silently
        unfetchable: the provider gets nothing to condition on and falls
        back to generating from the prompt text alone, exactly the "ignores
        the reference photo entirely" failure (see
        `app.providers.aihubmix_media._image_reference_urls`). Every other
        `app_env` is expected to publish a real internet-reachable public
        endpoint (a CDN/public bucket domain, `s3_public_endpoint_url` or
        `cos_public_endpoint_url` depending on `storage_backend`), where
        handing over a URL instead is strictly cheaper — the provider fetches
        once instead of every reference byte round-tripping through our own
        request body.
        """
        return self.app_env in ("local", "test")

    # The Agno console is an operator tool that exposes model bindings and lets
    # a human drive agents interactively, so it stays off unless asked for.
    agent_os_enabled: bool = False

    # NoDecode: the env value is a plain comma-separated string, not JSON.
    #
    # The default covers both hostnames the dev server answers on and the port
    # Playwright serves the production build from. `localhost` and `127.0.0.1`
    # are separate origins to a browser, so listing only one makes credentialed
    # requests fail depending on which URL the developer happened to open.
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:3100",
            "http://127.0.0.1:3100",
        ]
    )
    log_level: str = "INFO"
    otel_exporter: Literal["console", "otlp", "none"] = "console"
    otel_endpoint: str = ""

    @field_validator("jwt_secret", "admin_jwt_secret", "mcp_jwt_secret")
    @classmethod
    def _hmac_secrets_meet_hs256_minimum(cls, value: str) -> str:
        if len(value.encode("utf-8")) < 32:
            raise ValueError("must be at least 32 bytes for HS256 (RFC 7518 Section 3.2)")
        return value

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @model_validator(mode="after")
    def _reject_default_secrets_in_production(self) -> Settings:
        """A default that only ever guarded a handful of routes (the seed
        endpoint, admin data export) is not the same as a secret an attacker
        cannot look up in this very file. `app_env == "production"` with any
        of these four still at their shipped value must refuse to boot
        rather than silently accept forgeable sessions and a forgeable
        payment webhook signature.
        """
        if self.app_env != "production":
            return self
        defaults = {
            "jwt_secret": _DEFAULT_JWT_SECRET,
            "admin_jwt_secret": _DEFAULT_ADMIN_JWT_SECRET,
            "mcp_jwt_secret": _DEFAULT_MCP_JWT_SECRET,
            "payment_webhook_secret": _DEFAULT_PAYMENT_WEBHOOK_SECRET,
        }
        leaked = sorted(
            name for name, default in defaults.items() if getattr(self, name) == default
        )
        if leaked:
            joined = ", ".join(leaked)
            raise ValueError(
                f"refusing to start in production with repo-default secret(s): {joined}. "
                "Set a real value for each via the environment before deploying."
            )
        return self

    # HTTP-only deployments (no TLS terminator in front of the API) cannot set
    # a `Secure` cookie: the browser will accept it but never send it back, so
    # login silently breaks. Leave unset to inherit `is_production`; set
    # explicitly to decouple the cookie flag from the rest of production
    # hardening (e.g. the seed-endpoint refusal), which must stay on.
    cookie_secure_override: bool | None = Field(default=None, alias="COOKIE_SECURE")

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def cookie_secure(self) -> bool:
        if self.cookie_secure_override is None:
            return self.is_production
        return self.cookie_secure_override


@lru_cache
def get_settings() -> Settings:
    return Settings()
