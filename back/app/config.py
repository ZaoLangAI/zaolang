"""Application settings.

Secrets are only ever read from the environment. Nothing in this module may be
logged, echoed through the config centre, or placed into an agent prompt.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

LlmMode = Literal["openai_compatible", "stub", "auto"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    app_env: Literal["local", "test", "ci", "production"] = "local"
    app_version: str = "0.0.0-dev"
    api_base_url: str = "http://localhost:8000"
    web_base_url: str = "http://localhost:3000"

    database_url: str = "postgresql+psycopg://zaolang:zaolang@localhost:5433/zaolang"
    test_database_url: str = "postgresql+psycopg://zaolang:zaolang@localhost:5433/zaolang_test"
    redis_url: str = "redis://localhost:6380/0"

    # HS256 requires >= 32 bytes (RFC 7518 §3.2 / PyJWT). Local defaults are
    # random placeholders only — rotate before any shared or production deploy.
    jwt_secret: str = "k9Yxvz5CCVmGk9OKwnnBF6VfsWs5VS8r21kmQZ9DSsc"
    admin_jwt_secret: str = "dbTYs3wmf9v5Hc6ZJwLivNUAA0t1NpX4b_eLZX53G5E"
    mcp_jwt_secret: str = "m8Kq2nR4vX7pL1sD9wC6hB3tY0zF5jA2uE8iQ4oN7gM"
    payment_webhook_secret: str = "dev-only-change-me-webhook"
    access_token_ttl_seconds: int = 60 * 30
    refresh_token_ttl_seconds: int = 60 * 60 * 24 * 14
    admin_token_ttl_seconds: int = 60 * 60 * 8

    s3_endpoint_url: str = "http://localhost:9000"
    s3_public_endpoint_url: str = "http://localhost:9000"
    s3_region: str = "us-east-1"
    s3_bucket: str = "zaolang-media"
    s3_access_key: str = "zaolang"
    s3_secret_key: str = "zaolang-secret"
    upload_url_ttl_seconds: int = 60 * 10
    download_url_ttl_seconds: int = 60 * 15

    # Operator/test intent only. Endpoint URLs, keys, timeouts and retry
    # counts all live in the `llm_providers` platform config now — see
    # `app/llm/client.py` and `zaolang-agent-gateway`.
    llm_mode: LlmMode = "auto"

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
