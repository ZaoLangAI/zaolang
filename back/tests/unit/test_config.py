"""`Settings` must refuse to construct at all — not just warn — when
`app_env == "production"` and a signing secret is still the value this repo
ships in `config.py`. A default that only ever gated a handful of routes
(the seed endpoint, admin data export) is not the same as a secret an
attacker cannot read straight out of version control.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import (
    _DEFAULT_ADMIN_JWT_SECRET,
    _DEFAULT_JWT_SECRET,
    _DEFAULT_MCP_JWT_SECRET,
    _DEFAULT_PAYMENT_WEBHOOK_SECRET,
    Settings,
)

# 32+ bytes, distinct from every shipped default — a stand-in "real" secret.
_OVERRIDE_SECRET = "a-real-secret-rotated-for-this-deploy-1234567890"

_ALL_OVERRIDES = {
    "jwt_secret": _OVERRIDE_SECRET,
    "admin_jwt_secret": _OVERRIDE_SECRET + "-admin",
    "mcp_jwt_secret": _OVERRIDE_SECRET + "-mcp",
    "payment_webhook_secret": _OVERRIDE_SECRET + "-webhook",
}


def _settings(**overrides: str) -> Settings:
    return Settings(app_env="production", _env_file=None, **{**_ALL_OVERRIDES, **overrides})


@pytest.mark.parametrize(
    "field, default",
    [
        ("jwt_secret", _DEFAULT_JWT_SECRET),
        ("admin_jwt_secret", _DEFAULT_ADMIN_JWT_SECRET),
        ("mcp_jwt_secret", _DEFAULT_MCP_JWT_SECRET),
        ("payment_webhook_secret", _DEFAULT_PAYMENT_WEBHOOK_SECRET),
    ],
)
def test_production_refuses_to_start_with_any_one_default_secret(field: str, default: str) -> None:
    with pytest.raises(ValidationError, match="refusing to start in production"):
        _settings(**{field: default})


def test_production_refuses_to_start_with_every_secret_still_default() -> None:
    with pytest.raises(ValidationError, match="refusing to start in production"):
        Settings(app_env="production", _env_file=None)


def test_production_starts_once_every_secret_is_overridden() -> None:
    settings = _settings()
    assert settings.jwt_secret == _OVERRIDE_SECRET


def test_a_non_production_env_is_unaffected_by_the_shipped_defaults() -> None:
    for app_env in ("local", "test", "ci"):
        settings = Settings(app_env=app_env, _env_file=None)
        assert settings.jwt_secret == _DEFAULT_JWT_SECRET
