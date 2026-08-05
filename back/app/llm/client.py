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
from sqlalchemy.orm import Session

from app.config import get_settings
from app.llm import capabilities, failover
from app.llm.normalize import NormalizedResponse, normalize_completion
from app.llm.stub import stub_completion
from app.platform_config import service as config_service
from app.platform_config.schemas import LlmProviderConfig, LlmProviderEndpoint

logger = logging.getLogger(__name__)

# Reasoning models spend budget on hidden thinking before emitting anything, so
# a request that would fit in 512 visible tokens still needs far more headroom.
REASONING_TOKEN_FLOOR = 2048

# Used for the legacy single-endpoint path (no `llm_providers` configured yet)
# and as the id recorded on `AgentRun` in that case.
LEGACY_ENDPOINT_ID = "legacy"


@dataclass(slots=True)
class LlmCallResult:
    response: NormalizedResponse
    mode: str
    degraded: bool
    degrade_reason: str | None
    latency_ms: int
    endpoint_id: str = LEGACY_ENDPOINT_ID


@lru_cache
def get_client() -> OpenAI:
    """The legacy single endpoint, from environment settings.

    Kept as the fallback so a deploy with an empty `llm_providers` config (the
    default) still works without any seed data.
    """
    settings = get_settings()
    return OpenAI(
        api_key=settings.llm_api_key or "not-configured",
        base_url=settings.llm_base_url,
        timeout=settings.llm_timeout_seconds,
        max_retries=0,  # Retries are handled here so each attempt is recorded.
    )


@lru_cache(maxsize=64)
def _get_client_for_endpoint(base_url: str, api_key: str, timeout_ms: int) -> OpenAI:
    return OpenAI(
        api_key=api_key or "not-configured",
        base_url=base_url,
        timeout=timeout_ms / 1000,
        max_retries=0,
    )


def _client_for(endpoint: LlmProviderEndpoint) -> OpenAI:
    return _get_client_for_endpoint(endpoint.base_url, endpoint.api_key, endpoint.timeout_ms)


def reset_client_cache() -> None:
    get_client.cache_clear()
    _get_client_for_endpoint.cache_clear()


def complete(
    *,
    session: Session,
    agent_name: str,
    model: str,
    messages: list[dict[str, str]],
    max_tokens: int = 1024,
    temperature: float = 0.2,
    expect_json: bool = True,
    reasoning_model: bool = False,
) -> LlmCallResult:
    """Runs one agent inference and normalises whatever comes back.

    `agent_name` doubles as the failover pool's scenario tag: an endpoint
    configured with `scenario_tags: ["planner"]` is only offered planner
    calls, while `"general"` endpoints take any agent's traffic.
    """
    settings = get_settings()
    mode = settings.effective_llm_mode
    started = time.perf_counter()

    if mode == "stub":
        stub_response = stub_completion(agent_name=agent_name, messages=messages, model=model)
        return LlmCallResult(
            response=stub_response,
            mode="stub",
            degraded=False,
            degrade_reason=None,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )

    budget = max(max_tokens, REASONING_TOKEN_FLOOR) if reasoning_model else max_tokens
    provider_config = config_service.get_typed(session, "llm_providers", LlmProviderConfig)
    endpoints = failover.eligible_candidates(provider_config, agent_name)

    last_error: Exception | None = None
    tried_endpoint = False

    for endpoint_id, endpoint in endpoints:
        tried_endpoint = True
        with failover.lease(endpoint_id):
            response, budget, error = _attempt_endpoint(
                client=_client_for(endpoint),
                settings=settings,
                model=model,
                messages=messages,
                budget=budget,
                temperature=temperature,
                expect_json=expect_json,
            )
        failover.record_outcome(
            endpoint_id,
            success=response is not None,
            failure_threshold=provider_config.circuit_breaker_failure_threshold,
            cooldown_s=provider_config.circuit_breaker_cooldown_s,
        )
        if response is not None:
            return LlmCallResult(
                response=response,
                mode="openai_compatible",
                degraded=False,
                degrade_reason=None,
                latency_ms=int((time.perf_counter() - started) * 1000),
                endpoint_id=endpoint_id,
            )
        last_error = error

    if not tried_endpoint:
        # No `llm_providers` configured (the default), or every configured
        # endpoint was unavailable (breaker open / at capacity): fall back to
        # the single legacy endpoint so a fresh deploy still works.
        response, _budget, error = _attempt_endpoint(
            client=get_client(),
            settings=settings,
            model=model,
            messages=messages,
            budget=budget,
            temperature=temperature,
            expect_json=expect_json,
        )
        if response is not None:
            return LlmCallResult(
                response=response,
                mode="openai_compatible",
                degraded=False,
                degrade_reason=None,
                latency_ms=int((time.perf_counter() - started) * 1000),
                endpoint_id=LEGACY_ENDPOINT_ID,
            )
        last_error = error

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


def _attempt_endpoint(
    *,
    client: OpenAI,
    settings: Any,
    model: str,
    messages: list[dict[str, str]],
    budget: int,
    temperature: float,
    expect_json: bool,
) -> tuple[NormalizedResponse | None, int, Exception | None]:
    """One endpoint's full retry loop, isolated so `complete()` can move on to
    the next failover candidate without repeating this logic."""
    # Two extra slots beyond the configured retries so that discovering a
    # parameter incompatibility does not consume a real retry.
    attempts = settings.llm_max_retries + 3
    last_error: Exception | None = None

    for attempt in range(attempts):
        try:
            raw = _call_gateway(
                client=client,
                model=model,
                messages=messages,
                max_tokens=budget,
                temperature=temperature,
                expect_json=expect_json,
            )
            response = normalize_completion(raw, expect_json=expect_json)

            # A truncated reasoning model produced no usable payload: one retry
            # with a larger budget is cheaper than moving to the next endpoint.
            if (
                expect_json
                and response.data is None
                and response.truncated
                and attempt + 1 < attempts
            ):
                budget = min(budget * 2, 32_768)
                continue

            return response, budget, None
        except BadRequestError as exc:
            # A rejected parameter is a capability signal, not an outage.
            if capabilities.learn_from_error(model, str(exc)):
                logger.info("adjusted request shape for %s: %s", model, capabilities.get(model))
                continue
            last_error = exc
            logger.warning("llm gateway rejected request for %s: %s", model, exc)
            break
        except (OpenAIError, TimeoutError, ConnectionError) as exc:
            last_error = exc
            logger.warning(
                "llm gateway attempt %s/%s failed for %s: %s", attempt + 1, attempts, model, exc
            )

    return None, budget, last_error


def _call_gateway(
    *,
    client: OpenAI,
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

    return client.chat.completions.create(**kwargs)


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
