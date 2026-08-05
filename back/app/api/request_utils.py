"""Small request-derived helpers shared by every log-writing service."""

from __future__ import annotations

import datetime as dt

from fastapi import Request


def client_ip(request: Request | None) -> str | None:
    """Best-effort caller address. A forged `X-Forwarded-For` only lies about
    identity, never crashes anything, so it is trusted as-is behind the LB."""
    if request is None:
        return None
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()[:64]
    return request.client.host if request.client else None


def as_utc(value: dt.datetime) -> dt.datetime:
    """`datetime-local` inputs arrive without a timezone; treat them as UTC."""
    return value if value.tzinfo else value.replace(tzinfo=dt.UTC)
