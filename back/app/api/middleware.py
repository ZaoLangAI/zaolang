"""Cross-cutting HTTP middleware."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.observability.context import new_request_id, set_request_id

RequestHandler = Callable[[Request], Awaitable[Response]]


class CorrelationMiddleware(BaseHTTPMiddleware):
    """Assigns a request id and echoes it back.

    An inbound `X-Request-Id` is honoured so a trace started at the edge (or by
    the frontend) stays intact across the whole call.
    """

    async def dispatch(self, request: Request, call_next: RequestHandler) -> Response:
        incoming = request.headers.get("x-request-id", "").strip()
        request_id = incoming[:64] if incoming else new_request_id()
        set_request_id(request_id)
        request.state.request_id = request_id

        started = time.perf_counter()
        response = await call_next(request)
        response.headers["x-request-id"] = request_id
        response.headers["server-timing"] = f"app;dur={(time.perf_counter() - started) * 1000:.1f}"
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestHandler) -> Response:
        response = await call_next(request)
        response.headers.setdefault("x-content-type-options", "nosniff")
        response.headers.setdefault("referrer-policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("x-frame-options", "DENY")
        # Signed media URLs must never be cached by a shared proxy.
        if request.url.path.startswith("/v1/assets"):
            response.headers.setdefault("cache-control", "private, no-store")
        return response
