"""LLM gateway client with three operating modes.

* `openai_compatible` — always call the real gateway; surface failures.
* `stub` — never call out. Deterministic, so tests and CI produce identical
  results without a key and without cost.
* `auto` — call the gateway, fall back to the stub on error or timeout, and
  record the degradation so the ops console can show it.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from openai import BadRequestError, OpenAI, OpenAIError

from app.config import get_settings
from app.llm import capabilities
from app.llm.normalize import NormalizedResponse, normalize_completion
from app.llm.stub import stub_completion

logger = logging.getLogger(__name__)

# Reasoning models spend budget on hidden thinking before emitting anything, so
# a request that would fit in 512 visible tokens still needs far more headroom.
REASONING_TOKEN_FLOOR = 2048


@dataclass(slots=True)
class LlmCallResult:
    response: NormalizedResponse
    mode: str
    degraded: bool
    degrade_reason: str | None
    latency_ms: int


@lru_cache
def get_client() -> OpenAI:
    settings = get_settings()
    return OpenAI(
        api_key=settings.llm_api_key or "not-configured",
        base_url=settings.llm_base_url,
        timeout=settings.llm_timeout_seconds,
        max_retries=0,  # Retries are handled here so each attempt is recorded.
    )


def reset_client_cache() -> None:
    get_client.cache_clear()


def complete(
    *,
    agent_name: str,
    model: str,
    messages: list[dict[str, str]],
    max_tokens: int = 1024,
    temperature: float = 0.2,
    expect_json: bool = True,
    reasoning_model: bool = False,
) -> LlmCallResult:
    """Runs one agent inference and normalises whatever comes back."""
    settings = get_settings()
    mode = settings.effective_llm_mode
    started = time.perf_counter()

    if mode == "stub":
        response = stub_completion(agent_name=agent_name, messages=messages, model=model)
        return LlmCallResult(
            response=response,
            mode="stub",
            degraded=False,
            degrade_reason=None,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )

    budget = max(max_tokens, REASONING_TOKEN_FLOOR) if reasoning_model else max_tokens
    # Two extra slots beyond the configured retries so that discovering a
    # parameter incompatibility does not consume a real retry.
    attempts = settings.llm_max_retries + 3
    last_error: Exception | None = None

    for attempt in range(attempts):
        try:
            raw = _call_gateway(
                model=model,
                messages=messages,
                max_tokens=budget,
                temperature=temperature,
                expect_json=expect_json,
            )
            response = normalize_completion(raw, expect_json=expect_json)

            # A truncated reasoning model produced no usable payload: one retry
            # with a larger budget is cheaper than degrading to the stub.
            if (
                expect_json
                and response.data is None
                and response.truncated
                and attempt + 1 < attempts
            ):
                budget = min(budget * 2, 32_768)
                continue

            return LlmCallResult(
                response=response,
                mode="openai_compatible",
                degraded=False,
                degrade_reason=None,
                latency_ms=int((time.perf_counter() - started) * 1000),
            )
        except BadRequestError as exc:
            # A rejected parameter is a capability signal, not an outage.
            if capabilities.learn_from_error(model, str(exc)):
                logger.info("adjusted request shape for %s: %s", model, capabilities.get(model))
                continue
            last_error = exc
            logger.warning("llm gateway rejected request for %s: %s", agent_name, exc)
            break
        except (OpenAIError, TimeoutError, ConnectionError) as exc:
            last_error = exc
            logger.warning(
                "llm gateway attempt %s/%s failed for %s: %s",
                attempt + 1,
                attempts,
                agent_name,
                exc,
            )

    reason = type(last_error).__name__ if last_error else "unknown_error"
    if mode == "openai_compatible":
        # Strict mode: the caller asked for the real gateway, so failing loudly
        # is more honest than silently returning stub content.
        from app.domain.errors import ProviderTemporaryFailure

        raise ProviderTemporaryFailure(f"LLM 网关不可用: {reason}")

    response = stub_completion(agent_name=agent_name, messages=messages, model=model)
    return LlmCallResult(
        response=response,
        mode="auto",
        degraded=True,
        degrade_reason=reason,
        latency_ms=int((time.perf_counter() - started) * 1000),
    )


def _call_gateway(
    *,
    model: str,
    messages: list[dict[str, str]],
    max_tokens: int,
    temperature: float,
    expect_json: bool,
) -> Any:
    caps = capabilities.get(model)
    kwargs: dict[str, Any] = {"model": model, "messages": messages}

    if caps.uses_max_completion_tokens:
        kwargs["max_completion_tokens"] = max_tokens
    else:
        kwargs["max_tokens"] = max_tokens

    if caps.supports_temperature:
        kwargs["temperature"] = temperature
    elif caps.forced_temperature is not None:
        kwargs["temperature"] = caps.forced_temperature

    if expect_json and caps.supports_response_format:
        # Honoured by some models and ignored by others; normalisation handles
        # the rest, so asking is worthwhile where it is accepted.
        kwargs["response_format"] = {"type": "json_object"}

    return get_client().chat.completions.create(**kwargs)


def probe() -> dict[str, Any]:
    """Connectivity check for the ops console health panel."""
    settings = get_settings()
    mode = settings.effective_llm_mode
    if mode == "stub":
        return {"mode": mode, "reachable": False, "detail": "stub 模式未连接网关"}

    started = time.perf_counter()
    try:
        models = get_client().models.list()
        count = len(getattr(models, "data", []) or [])
        return {
            "mode": mode,
            "reachable": True,
            "model_count": count,
            "latency_ms": int((time.perf_counter() - started) * 1000),
        }
    except Exception as exc:
        return {"mode": mode, "reachable": False, "detail": type(exc).__name__}
