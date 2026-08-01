"""Uniform error envelope.

Every failure — domain error, validation error or unexpected exception — leaves
the API in the same shape, so the frontend has exactly one error path to handle:

    {"error": {"code": ..., "message": ..., "details": {...}, "request_id": ...}}
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.domain.errors import DomainError, RateLimited
from app.observability.context import get_request_id

logger = logging.getLogger(__name__)


def error_body(
    code: str, message: str, *, details: dict[str, Any] | None = None, request_id: str | None = None
) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
            "request_id": request_id or get_request_id(),
        }
    }


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def _domain_error(_: Request, exc: DomainError) -> JSONResponse:
        headers: dict[str, str] = {}
        if isinstance(exc, RateLimited):
            # Without this the client can only guess when to come back, and
            # guessing usually means retrying immediately.
            headers["Retry-After"] = str(exc.retry_after_seconds)
        return JSONResponse(
            status_code=exc.http_status,
            content=error_body(exc.code, exc.message, details=exc.details),
            headers=headers or None,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Field paths are surfaced so the UI can attach messages inline instead
        # of showing one generic banner.
        fields = {
            ".".join(str(part) for part in error["loc"][1:]): error["msg"] for error in exc.errors()
        }
        return JSONResponse(
            status_code=422,
            content=error_body("VALIDATION_FAILED", "请求参数不合法。", details={"fields": fields}),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {
            401: "AUTH_REQUIRED",
            403: "FORBIDDEN",
            404: "NOT_FOUND",
            405: "METHOD_NOT_ALLOWED",
            429: "RATE_LIMITED",
        }.get(exc.status_code, "HTTP_ERROR")
        return JSONResponse(status_code=exc.status_code, content=error_body(code, str(exc.detail)))

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        # The request id is the only thing the user gets; the detail stays in
        # logs so internal structure is never leaked to a client.
        logger.exception("unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content=error_body("INTERNAL_ERROR", "服务暂时不可用，请稍后重试。"),
        )
