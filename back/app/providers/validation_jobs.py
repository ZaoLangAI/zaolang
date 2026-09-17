"""Ephemeral store for in-flight admin endpoint connectivity probes.

Image generation can take tens of seconds. The validate HTTP request must
return immediately; the console polls this store for the finished result.
Nothing here is durable or secret: TTL-bound Redis JSON, never an api_key.
"""

from __future__ import annotations

import json
import time
from typing import Any

from app.api.rate_limit import get_redis
from app.api.schemas.admin import LlmProviderValidationJob, LlmProviderValidationResult
from app.models.base import new_id

_KEY_PREFIX = "admin:llm-validate:"
_MIN_TTL_SECONDS = 180


def ttl_seconds(timeout_ms: int) -> int:
    return max(timeout_ms // 1000 + 60, _MIN_TTL_SECONDS)


def create_running(*, endpoint_id: str, timeout_ms: int) -> LlmProviderValidationJob:
    validation_id = new_id("val")
    payload: dict[str, Any] = {
        "validation_id": validation_id,
        "endpoint_id": endpoint_id,
        "status": "running",
        "started_at_ms": int(time.time() * 1000),
        "timeout_ms": timeout_ms,
        "result": None,
    }
    _save(validation_id, payload, ttl_seconds(timeout_ms))
    return _to_job(payload)


def complete(validation_id: str, result: LlmProviderValidationResult) -> None:
    payload = _load(validation_id)
    if payload is None:
        return
    payload["status"] = "completed"
    payload["result"] = result.model_dump(mode="json")
    _save(validation_id, payload, ttl_seconds(int(payload["timeout_ms"])))


def get(endpoint_id: str, validation_id: str) -> LlmProviderValidationJob | None:
    payload = _load(validation_id)
    if payload is None or payload.get("endpoint_id") != endpoint_id:
        return None
    return _to_job(payload)


def _key(validation_id: str) -> str:
    return f"{_KEY_PREFIX}{validation_id}"


def _save(validation_id: str, payload: dict[str, Any], ttl: int) -> None:
    get_redis().set(_key(validation_id), json.dumps(payload), ex=ttl)


def _load(validation_id: str) -> dict[str, Any] | None:
    raw = get_redis().get(_key(validation_id))
    if not isinstance(raw, str) or not raw:
        return None
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


def _to_job(payload: dict[str, Any]) -> LlmProviderValidationJob:
    started_ms = int(payload["started_at_ms"])
    result_data = payload.get("result")
    return LlmProviderValidationJob(
        validation_id=str(payload["validation_id"]),
        status="completed" if payload.get("status") == "completed" else "running",
        elapsed_ms=max(0, int(time.time() * 1000) - started_ms),
        timeout_ms=int(payload["timeout_ms"]),
        result=(
            LlmProviderValidationResult.model_validate(result_data)
            if isinstance(result_data, dict)
            else None
        ),
    )
