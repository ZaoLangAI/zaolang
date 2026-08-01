"""Structured logging with correlation fields attached automatically."""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

from app.observability.context import correlation_fields

# Never log these, whatever the caller passes.
REDACTED_KEYS = frozenset(
    {
        "password",
        "password_hash",
        "authorization",
        "cookie",
        "api_key",
        "llm_api_key",
        "secret",
        "jwt_secret",
        "signature",
        "token",
        "refresh_token",
    }
)


def redact(payload: dict[str, Any]) -> dict[str, Any]:
    """Masks sensitive values recursively before anything reaches a log sink."""
    cleaned: dict[str, Any] = {}
    for key, value in payload.items():
        if key.lower() in REDACTED_KEYS:
            cleaned[key] = "***"
        elif isinstance(value, dict):
            cleaned[key] = redact(value)
        else:
            cleaned[key] = value
    return cleaned


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            **correlation_fields(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        extra = getattr(record, "extra_fields", None)
        if isinstance(extra, dict):
            payload.update(redact(extra))
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    # uvicorn duplicates access lines that carry no correlation id.
    logging.getLogger("uvicorn.access").handlers = []
