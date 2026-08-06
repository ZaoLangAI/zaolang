"""Liveness and readiness probes.

`/healthz` answers whether the process is up; `/readyz` answers whether it can
actually serve traffic. Keeping them separate stops a transient database blip
from causing an orchestrator to kill an otherwise healthy process.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Response
from sqlalchemy import text

from app.config import get_settings
from app.db import session_scope

router = APIRouter(tags=["health"])


@router.get("/healthz")
def healthz() -> dict[str, Any]:
    settings = get_settings()
    return {
        "status": "ok",
        "version": settings.app_version,
        "env": settings.app_env,
        "llm_mode": settings.llm_mode,
        "source": settings.source_repository_url,
    }


@router.get("/readyz")
def readyz(response: Response) -> dict[str, Any]:
    checks = {"postgres": _check_postgres(), "redis": _check_redis()}
    ready = all(checks.values())
    if not ready:
        response.status_code = 503
    return {"ready": ready, "checks": checks}


def _check_postgres() -> bool:
    try:
        with session_scope() as session:
            session.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def _check_redis() -> bool:
    try:
        from app.api.rate_limit import get_redis

        return bool(get_redis().ping())
    except Exception:
        return False
