"""Correlation identifiers.

`request_id` follows a call from the HTTP edge through domain services, Celery
tasks, provider attempts and agent runs, so one identifier reconstructs the
whole chain in the ops console.
"""

from __future__ import annotations

import secrets
from contextvars import ContextVar

_request_id: ContextVar[str] = ContextVar("request_id", default="")
_user_id: ContextVar[str] = ContextVar("user_id", default="")
_job_id: ContextVar[str] = ContextVar("job_id", default="")


def new_request_id() -> str:
    return f"req_{secrets.token_hex(12)}"


def set_request_id(value: str) -> None:
    _request_id.set(value)


def get_request_id() -> str:
    return _request_id.get()


def set_user_id(value: str) -> None:
    _user_id.set(value)


def get_user_id() -> str:
    return _user_id.get()


def set_job_id(value: str) -> None:
    _job_id.set(value)


def get_job_id() -> str:
    return _job_id.get()


def correlation_fields() -> dict[str, str]:
    return {
        key: value
        for key, value in (
            ("request_id", get_request_id()),
            ("user_id", get_user_id()),
            ("job_id", get_job_id()),
        )
        if value
    }
