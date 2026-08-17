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
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from openai import BadRequestError, OpenAI, OpenAIError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.llm import capabilities, failover
from app.llm.normalize import NormalizedResponse, normalize_completion
from app.llm.stub import stub_completion, stub_stream_completion
from app.platform_config import service as config_service
from app.platform_config.schemas import LlmProviderConfig, LlmProviderEndpoint

logger = logging.getLogger(__name__)

# Reasoning models spend budget on hidden thinking before emitting anything, so
# a request that would fit in 512 visible tokens still needs far more headroom.
REASONING_TOKEN_FLOOR = 2048

# Recorded on `AgentRun` / returned to callers when nothing in `llm_providers`
# matched — there is no per-endpoint id to report in that case.
NO_ENDPOINT_ID = "none"
# AgentProfile has no model (and none was inherited). Never invent a name.
NO_MODEL_BOUND = "no_model_bound"

# Endpoint timeout and concurrency remain model-level settings. These bounded
# gateway safeguards are deliberately code constants, not a second global
# reliability configuration surface.
MAX_TRANSPORT_RETRIES = 1
CIRCUIT_BREAKER_FAILURE_THRESHOLD = 5
CIRCUIT_BREAKER_COOLDOWN_SECONDS = 60


@dataclass(slots=True)
class LlmCallResult:
    response: NormalizedResponse
    mode: str
    degraded: bool
    degrade_reason: str | None
    latency_ms: int
    endpoint_id: str = NO_ENDPOINT_ID


@dataclass(slots=True)
class StreamResult:
    """Populated in place by `stream_complete` as its generator is drained.

    Unlike `LlmCallResult`, which is returned once `complete()` finishes, a
    streaming caller needs to read text as it arrives — so the caller passes
    this container in and only reads it back after the generator is fully
    exhausted (mirrors how `run_agent_stream` uses it in `app.agents.base`).
    """

    text: str = ""
    mode: str = ""
    degraded: bool = False
    degrade_reason: str | None = None
    latency_ms: int = 0
    endpoint_id: str = NO_ENDPOINT_ID
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0


@lru_cache(maxsize=64)
def _get_client_for_endpoint(base_url: str, api_key: str, timeout_ms: int) -> OpenAI:
    return OpenAI(
        api_key=api_key or "not-configured",
        base_url=base_url,
        timeout=timeout_ms / 1000,
        max_retries=0,  # Retries are handled here so each attempt is recorded.
    )


def client_for_endpoint(endpoint: LlmProviderEndpoint) -> OpenAI:
    """The OpenAI SDK client for one `llm_providers` endpoint.

    Public (not `_`-prefixed) because `app/teams/generation_gateway.py` and
    the live connectivity tests build clients for a specific endpoint too,
    and must share this cache rather than constructing their own.
    """
    return _get_client_for_endpoint(endpoint.base_url, endpoint.api_key, endpoint.timeout_ms)


def reset_client_cache() -> None:
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
    preferred_endpoint_ids: Sequence[str] = (),
) -> LlmCallResult:
    """Runs one agent inference and normalises whatever comes back.

    Every agent role (safety/planner/quality/copy) shares the same
    `kind="general"` endpoint pool now — there is no per-agent scenario tag.
    `agent_name` is kept only because `stub_completion` uses it to vary its
    deterministic output.

    `preferred_endpoint_ids` is the provider order an `AgentProfile` pinned
    (default, then backup). When present, no unselected provider may serve
    the call; an unbound profile uses the compatible shared pool.

    `model` is where the call starts — the model declared on the binding's
    default endpoint. Each endpoint serves exactly one model, so failing over
    to the next candidate runs *that* endpoint's model rather than skipping it
    for naming something different.
    """
    settings = get_settings()
    mode = settings.llm_mode
    started = time.perf_counter()
    chosen = (model or "").strip()

    if not chosen:
        stub_response = stub_completion(agent_name=agent_name, messages=messages, model="")
        stub_response.model = ""
        return LlmCallResult(
            response=stub_response,
            mode=mode if mode == "stub" else "auto",
            degraded=True,
            degrade_reason=NO_MODEL_BOUND,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )

    if mode == "stub":
        stub_response = stub_completion(agent_name=agent_name, messages=messages, model=chosen)
        return LlmCallResult(
            response=stub_response,
            mode="stub",
            degraded=False,
            degrade_reason=None,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )

    budget = max(max_tokens, REASONING_TOKEN_FLOOR) if reasoning_model else max_tokens
    provider_config = config_service.get_typed(session, "llm_providers", LlmProviderConfig)
    endpoints = failover.eligible_candidates(provider_config, preferred_ids=preferred_endpoint_ids)

    last_error: Exception | None = None
    tried_endpoint = False

    for endpoint_id, endpoint in endpoints:
        if not endpoint.model:
            continue
        tried_endpoint = True
        with failover.lease(endpoint_id):
            response, budget, error = _attempt_endpoint(
                client=client_for_endpoint(endpoint),
                max_retries=MAX_TRANSPORT_RETRIES,
                model=endpoint.model,
                messages=messages,
                budget=budget,
                temperature=temperature,
                expect_json=expect_json,
            )
        failover.record_outcome(
            endpoint_id,
            success=response is not None,
            failure_threshold=CIRCUIT_BREAKER_FAILURE_THRESHOLD,
            cooldown_s=CIRCUIT_BREAKER_COOLDOWN_SECONDS,
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
        # Nothing in `llm_providers` is available (empty pool, or every
        # candidate is breaker-open/at capacity). There is no env-level
        # endpoint to fall back to any more — an operator has to configure one
        # at `/admin/models`.
        reason = "no_endpoint_configured"
        if mode == "openai_compatible":
            from app.domain.errors import ProviderTemporaryFailure

            raise ProviderTemporaryFailure("未配置任何可用的 LLM 网关端点。")
        response = stub_completion(agent_name=agent_name, messages=messages, model=chosen)
        return LlmCallResult(
            response=response,
            mode="auto",
            degraded=True,
            degrade_reason=reason,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )

    reason = type(last_error).__name__ if last_error else "unknown_error"
    if mode == "openai_compatible":
        # Strict mode: the caller asked for the real gateway, so failing loudly
        # is more honest than silently returning stub content.
        from app.domain.errors import ProviderTemporaryFailure

        raise ProviderTemporaryFailure(f"LLM 网关不可用: {reason}")

    response = stub_completion(agent_name=agent_name, messages=messages, model=chosen)
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
    max_retries: int,
    model: str,
    messages: list[dict[str, str]],
    budget: int,
    temperature: float,
    expect_json: bool,
) -> tuple[NormalizedResponse | None, int, Exception | None]:
    """One endpoint's full retry loop, isolated so `complete()` can move on to
    the next failover candidate without repeating this logic."""
    transport_limit = max_retries + 1
    transport_attempt = 0
    compatibility_adjusted = False
    truncation_expanded = False
    last_error: Exception | None = None

    while transport_attempt < transport_limit:
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
                and not truncation_expanded
            ):
                truncation_expanded = True
                budget = min(budget * 2, 32_768)
                continue

            return response, budget, None
        except BadRequestError as exc:
            # A rejected parameter is a capability signal, not an outage.
            if not compatibility_adjusted and capabilities.learn_from_error(model, str(exc)):
                compatibility_adjusted = True
                logger.info("adjusted request shape for %s: %s", model, capabilities.get(model))
                continue
            last_error = exc
            logger.warning("llm gateway rejected request for %s: %s", model, exc)
            break
        except (OpenAIError, TimeoutError, ConnectionError) as exc:
            transport_attempt += 1
            last_error = exc
            logger.warning(
                "llm gateway transport attempt %s/%s failed for %s: %s",
                transport_attempt,
                transport_limit,
                model,
                exc,
            )

    return None, budget, last_error


def call_gateway_once(
    *,
    client: OpenAI,
    model: str,
    messages: list[dict[str, str]],
    max_tokens: int,
    temperature: float,
    expect_json: bool,
) -> Any:
    """Send one production-shaped request without failover, retry, or stub."""
    return _call_gateway(
        client=client,
        model=model,
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
        expect_json=expect_json,
    )


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


def stream_complete(
    *,
    session: Session,
    agent_name: str,
    model: str,
    messages: list[dict[str, str]],
    result: StreamResult,
    max_tokens: int = 2048,
    temperature: float = 0.4,
    reasoning_model: bool = False,
    preferred_endpoint_ids: Sequence[str] = (),
) -> Iterator[str]:
    """Streams text deltas for one agent turn, filling `result` as it goes.

    This is a separate path from `complete()`, not a mode of it: JSON-mode
    responses are parsed as one blob (`normalize_completion`), but a
    streaming turn is plain/mixed text handed to the caller token-by-token,
    so there is nothing to normalize until the generator is exhausted.

    Deliberately no mid-stream failover: once a chunk has been yielded from
    an endpoint, that endpoint is used for the rest of the turn even if it
    later errors, because a chat bubble that is already mid-sentence cannot
    silently restart on a different provider without a visibly broken UI. A
    connection that fails before yielding anything still moves on to the
    next candidate, same as `complete()`.
    """
    settings = get_settings()
    mode = settings.llm_mode
    started = time.perf_counter()
    chosen = (model or "").strip()
    prompt_tokens = sum(len(m.get("content", "")) for m in messages) // 4

    def _finalize(
        *,
        text: str,
        result_mode: str,
        degraded: bool,
        reason: str | None,
        endpoint_id: str,
        served_model: str | None = None,
    ) -> None:
        result.text = text
        result.mode = result_mode
        result.degraded = degraded
        result.degrade_reason = reason
        result.endpoint_id = endpoint_id
        # Whichever endpoint answered decides the model — on failover that is
        # not the one the binding started with.
        result.model = served_model or chosen
        result.prompt_tokens = prompt_tokens
        result.completion_tokens = len(text) // 4
        result.latency_ms = int((time.perf_counter() - started) * 1000)

    if not chosen:
        text = stub_stream_completion(agent_name=agent_name, messages=messages)
        yield text
        _finalize(
            text=text,
            result_mode=mode if mode == "stub" else "auto",
            degraded=True,
            reason=NO_MODEL_BOUND,
            endpoint_id=NO_ENDPOINT_ID,
        )
        return

    if mode == "stub":
        text = stub_stream_completion(agent_name=agent_name, messages=messages)
        yield text
        _finalize(
            text=text, result_mode="stub", degraded=False, reason=None, endpoint_id=NO_ENDPOINT_ID
        )
        result.model = f"stub:{chosen}"
        return

    provider_config = config_service.get_typed(session, "llm_providers", LlmProviderConfig)
    endpoints = failover.eligible_candidates(provider_config, preferred_ids=preferred_endpoint_ids)

    last_error: Exception | None = None
    tried_endpoint = False

    for endpoint_id, endpoint in endpoints:
        if not endpoint.model:
            continue
        tried_endpoint = True
        client = client_for_endpoint(endpoint)
        accumulated: list[str] = []
        error: Exception | None = None
        with failover.lease(endpoint_id):
            try:
                for delta in _stream_gateway(
                    client=client,
                    model=endpoint.model,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                ):
                    accumulated.append(delta)
                    yield delta
            except (OpenAIError, TimeoutError, ConnectionError) as exc:
                error = exc
                logger.warning(
                    "llm gateway stream failed for %s (endpoint=%s): %s",
                    endpoint.model,
                    endpoint_id,
                    exc,
                )
        if accumulated or error is None:
            failover.record_outcome(
                endpoint_id,
                success=True,
                failure_threshold=CIRCUIT_BREAKER_FAILURE_THRESHOLD,
                cooldown_s=CIRCUIT_BREAKER_COOLDOWN_SECONDS,
            )
            _finalize(
                text="".join(accumulated),
                result_mode="openai_compatible",
                degraded=error is not None,
                reason=type(error).__name__ if error else None,
                endpoint_id=endpoint_id,
                served_model=endpoint.model,
            )
            return
        failover.record_outcome(
            endpoint_id,
            success=False,
            failure_threshold=CIRCUIT_BREAKER_FAILURE_THRESHOLD,
            cooldown_s=CIRCUIT_BREAKER_COOLDOWN_SECONDS,
        )
        last_error = error

    if not tried_endpoint:
        reason = "no_endpoint_configured"
        if mode == "openai_compatible":
            from app.domain.errors import ProviderTemporaryFailure

            raise ProviderTemporaryFailure("未配置任何可用的 LLM 网关端点。")
        text = stub_stream_completion(agent_name=agent_name, messages=messages)
        yield text
        _finalize(
            text=text, result_mode="auto", degraded=True, reason=reason, endpoint_id=NO_ENDPOINT_ID
        )
        return

    reason = type(last_error).__name__ if last_error else "unknown_error"
    if mode == "openai_compatible":
        from app.domain.errors import ProviderTemporaryFailure

        raise ProviderTemporaryFailure(f"LLM 网关不可用: {reason}")

    text = stub_stream_completion(agent_name=agent_name, messages=messages)
    yield text
    _finalize(
        text=text, result_mode="auto", degraded=True, reason=reason, endpoint_id=NO_ENDPOINT_ID
    )


def _stream_gateway(
    *,
    client: OpenAI,
    model: str,
    messages: list[dict[str, str]],
    max_tokens: int,
    temperature: float,
) -> Iterator[str]:
    """One streamed request, no retry/failover — `stream_complete` owns that."""
    caps = capabilities.get(model)
    kwargs: dict[str, Any] = {"model": model, "messages": messages, "stream": True}

    if caps.uses_max_completion_tokens:
        kwargs["max_completion_tokens"] = max_tokens
    else:
        kwargs["max_tokens"] = max_tokens

    if caps.supports_temperature:
        kwargs["temperature"] = temperature
    elif caps.forced_temperature is not None:
        kwargs["temperature"] = caps.forced_temperature

    stream = client.chat.completions.create(**kwargs)
    for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta


def probe(session: Session) -> dict[str, Any]:
    """Connectivity check for the ops console health panel.

    Picks the "general" primary endpoint if one exists, otherwise any enabled
    endpoint — there is no env-level endpoint to fall back to any more.
    """
    settings = get_settings()
    mode = settings.llm_mode
    if mode == "stub":
        return {"mode": mode, "reachable": False, "detail": "stub 模式未连接网关"}

    provider_config = config_service.get_typed(session, "llm_providers", LlmProviderConfig)
    candidates = failover.general_candidates(provider_config)
    if not candidates:
        return {"mode": mode, "reachable": False, "detail": "未配置任何网关端点"}
    _endpoint_id, endpoint = candidates[0]

    started = time.perf_counter()
    try:
        models = client_for_endpoint(endpoint).models.list()
        count = len(getattr(models, "data", []) or [])
        return {
            "mode": mode,
            "reachable": True,
            "model_count": count,
            "latency_ms": int((time.perf_counter() - started) * 1000),
        }
    except Exception as exc:
        return {"mode": mode, "reachable": False, "detail": type(exc).__name__}
