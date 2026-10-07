"""LLM gateway client.

Every call goes through the real, admin-configured gateway
(`llm_providers` platform config): there is no stub/mock mode and no silent
fallback. A model that is not bound, or a gateway that is unreachable, raises
`ProviderTemporaryFailure` immediately — an agent call either used the model
an operator actually configured, or it failed loudly enough to be noticed
and retried at the job level (see `app.workflows.runner`).
"""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Literal

from openai import BadRequestError, OpenAI, OpenAIError
from sqlalchemy.orm import Session

from app.domain.errors import NoCapableEndpoint, ProviderTemporaryFailure
from app.llm import capabilities, failover
from app.llm.normalize import (
    NormalizedResponse,
    normalize_completion,
    reasoning_text,
    reasoning_text_from_delta,
    strip_thinking,
)
from app.platform_config import service as config_service
from app.platform_config.schemas import LlmProviderConfig, LlmProviderEndpoint

logger = logging.getLogger(__name__)

# Recorded on `AgentRun` / returned to callers when nothing in `llm_providers`
# matched — there is no per-endpoint id to report in that case.
NO_ENDPOINT_ID = "none"

# Endpoint timeout and concurrency remain model-level settings. These bounded
# gateway safeguards are deliberately code constants, not a second global
# reliability configuration surface.
MAX_TRANSPORT_RETRIES = 1
CIRCUIT_BREAKER_FAILURE_THRESHOLD = 5
CIRCUIT_BREAKER_COOLDOWN_SECONDS = 60
# How long `complete()` waits for a slot when every healthy endpoint is at
# `max_concurrency`. A batch (a 12-cell scene matrix, a fill wave) puts more
# jobs on the safety/planner agents at once than a small pool has slots;
# without waiting the overflow failed outright as "no endpoint configured".
# Measured locally (glm-5.3-flash, 4 slots, 12 matrix cells): the last cell
# finished ~6 minutes after submit, so a 90s wait still failed half of them.
# 420s stays under the image task's 660s soft limit (`workers/tasks.py`).
CAPACITY_WAIT_SECONDS = 420.0
# Jittered so waiting workers do not wake in lockstep and re-collide.
CAPACITY_POLL_SECONDS = (0.5, 1.5)

# A wall-clock ceiling on one streaming attempt, independent of
# `endpoint.timeout_ms` (which only bounds the *idle* gap between bytes and
# therefore never fires against a slow-but-steady trickle of reasoning
# deltas). Checked once per delta rather than via a second thread — a
# reasoning model that streams live (the whole point of this contract change)
# gives this loop frequent chances to notice the clock; one that goes fully
# silent for this long is instead caught by `endpoint.timeout_ms` first.
# Thinking deltas do *not* reset this clock (a slow think would hang
# forever); 600s is the room a copy-enhance / script pass needs to finish
# JSON after a long think, not a per-delta idle.
STREAM_WALL_CLOCK_TIMEOUT_SECONDS = 600


@dataclass(slots=True)
class LlmCallResult:
    response: NormalizedResponse
    latency_ms: int
    endpoint_id: str = NO_ENDPOINT_ID
    # Raw reasoning trace collected while assembling the streamed completion.
    # Kept off `response.text` so a caller can persist/display it without
    # polluting the parsed JSON payload (see `AgentRun.thinking_text`).
    thinking: str = ""


@dataclass(slots=True)
class StreamResult:
    """Populated in place by `stream_complete` as its generator is drained.

    Unlike `LlmCallResult`, which is returned once `complete()` finishes, a
    streaming caller needs to read text as it arrives — so the caller passes
    this container in and only reads it back after the generator is fully
    exhausted (mirrors how `run_agent_stream` uses it in `app.agents.base`).
    """

    text: str = ""
    latency_ms: int = 0
    endpoint_id: str = NO_ENDPOINT_ID
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    # The full reasoning trace this call produced, whether or not it ended up
    # recovered into `text` (see `_stream_complete_from_endpoints`) — kept
    # separately so a caller can persist/display it without it being
    # entangled with the parsed answer. Raw, not `strip_thinking`-cleaned:
    # that cleanup is specifically for extracting an *answer* out of a
    # reasoning-only response, not for the display copy of the thinking
    # itself.
    thinking: str = ""


@dataclass(slots=True)
class StreamChunk:
    """One item from `stream_complete`'s iterator.

    `kind="content"` is the user-facing chat bubble text (same as the old
    plain-`str` contract). `kind="thinking"` is the model's reasoning text,
    now streamed live instead of only being recovered after the fact — see
    the module-level docstring on `stream_complete`.
    """

    kind: Literal["content", "thinking"]
    text: str


@dataclass(slots=True)
class StreamDelta:
    """One streamed chunk plus the fields `_stream_gateway` can recover.

    Tests and `stream_complete` read `content` for the chat bubble and
    `reasoning` / `finish_reason` after the iterator is drained.
    """

    content: str = ""
    reasoning: str = ""
    finish_reason: str = ""
    usage: dict[str, int] | None = None


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


# A chat message. `content` is usually a string; script-source image
# extract sends an OpenAI-style list of text / image_url parts. Such parts
# narrow failover to endpoints that declare the modality (see
# `_required_modalities`); timing is unchanged.
LlmMessage = dict[str, Any]

# Which `input_modalities` value an OpenAI-style content part needs.
_PART_MODALITIES: dict[str, str] = {"image_url": "image", "video_url": "video"}

# Flat prompt-size charge per image part. The real count depends on the
# provider's tiling and the image size, neither of which is known here; a
# ~1k-pixel image lands near this on the common VLMs, and counting nothing
# (the old behaviour) let `output_budget` promise context the image had
# already used.
IMAGE_PART_TOKEN_ESTIMATE = 1024


def _content_parts(messages: list[LlmMessage]) -> Iterator[dict[str, Any]]:
    for message in messages:
        content = message.get("content")
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict):
                    yield part


def _required_modalities(messages: list[LlmMessage]) -> frozenset[str]:
    """Input modalities beyond text that `messages` carry.

    Derived from the parts themselves rather than a new call argument, so a
    caller that sends an `image_url` part (script image extract) is routed
    to image-capable endpoints without changing how it calls `complete()`.
    """
    return frozenset(
        _PART_MODALITIES[part_type]
        for part in _content_parts(messages)
        if (part_type := part.get("type")) in _PART_MODALITIES
    )


def _content_char_len(content: object) -> int:
    if isinstance(content, str):
        return len(content)
    if isinstance(content, list):
        total = 0
        for part in content:
            if isinstance(part, str):
                total += len(part)
            elif isinstance(part, dict) and isinstance(part.get("text"), str):
                total += len(part["text"])
        return total
    return 0


def _prompt_tokens(messages: list[LlmMessage]) -> int:
    """Rough prompt size for context-window capping.

    The gateway does not always return usage on a stream, so both
    `complete()` and `stream_complete()` use the same estimate to decide
    how much of `endpoint.context_length` is left for the completion.
    """
    text_tokens = sum(_content_char_len(m.get("content")) for m in messages) // 4
    image_parts = sum(1 for part in _content_parts(messages) if part.get("type") == "image_url")
    return text_tokens + image_parts * IMAGE_PART_TOKEN_ESTIMATE


def _check_capable(
    config: LlmProviderConfig, preferred_ids: Sequence[str], required: frozenset[str]
) -> None:
    """Raises `NoCapableEndpoint` when no configured endpoint this call may
    use can read `required` — health and capacity aside, so a busy image
    endpoint still waits rather than reporting "none configured".

    `app.agents.base.effective_binding` already re-routes a binding whose
    endpoints all lack the modality to the capable shared pool; reaching the
    second branch means a caller pinned endpoints without going through it.
    """
    if not required:
        return
    capable = failover.general_candidates(config, required_modalities=required)
    if not capable:
        raise NoCapableEndpoint(required)
    if preferred_ids and not {endpoint_id for endpoint_id, _ in capable} & set(preferred_ids):
        raise NoCapableEndpoint(required)


_chunk_sink: ContextVar[Callable[[StreamChunk], None] | None] = ContextVar(
    "llm_chunk_sink", default=None
)


@contextmanager
def bind_on_chunk(handler: Callable[[StreamChunk], None] | None) -> Iterator[None]:
    """Binds a chunk sink for the current task — used by job nodes so every
    nested `run_agent` / `complete()` call publishes thinking without each
    agent wrapper growing an `on_chunk` argument."""
    token = _chunk_sink.set(handler)
    try:
        yield
    finally:
        _chunk_sink.reset(token)


def complete(
    *,
    session: Session,
    agent_name: str,
    model: str,
    messages: list[LlmMessage],
    max_tokens: int = 1024,
    temperature: float = 0.2,
    expect_json: bool = True,
    reasoning_model: bool = False,
    preferred_endpoint_ids: Sequence[str] = (),
    on_chunk: Callable[[StreamChunk], None] | None = None,
) -> LlmCallResult:
    """Runs one agent inference and normalises whatever comes back.

    Every agent role (safety/planner/quality/copy) shares the same
    `kind="general"` endpoint pool now — there is no per-agent scenario tag.
    `agent_name` plays no routing role here; it only makes the "which agent
    has no model configured" error legible to whoever reads it, and gives
    tests a real gateway seam to swap out (see `tests/fake_llm_gateway.py`)
    without also having to fake `app.agents.base`'s profile/prompt
    resolution.

    `preferred_endpoint_ids` is the provider order an `AgentProfile` pinned
    (default, then backup). When present, no unselected provider may serve
    the call; an unbound profile uses the compatible shared pool.

    `model` is where the call starts — the model declared on the binding's
    default endpoint. Each endpoint serves exactly one model, so failing over
    to the next candidate runs *that* endpoint's model rather than skipping it
    for naming something different.

    Transport is always a stream assembled back into one completion: reasoning
    deltas keep the connection alive (a silent glm-5.3-flash think no longer
    trips `endpoint.timeout_ms` as a wall clock). The caller still receives
    one `LlmCallResult`. Pass `on_chunk` (or bind `bind_on_chunk`) to observe
    thinking/content as they arrive; once a chunk has been handed over,
    failover and transport retry both stop.

    Messages carrying `image_url` / `video_url` parts only go to endpoints
    whose `input_modalities` declare that modality; when none is configured
    the call raises `NoCapableEndpoint` instead of trying a text-only model.

    Raises `ProviderTemporaryFailure` (never returns a fabricated result) when
    no model is bound, no endpoint is configured, or every eligible endpoint's
    call failed — the caller (an operator, or a job's own retry) needs an
    honest signal, not a plausible-looking answer nobody actually generated.
    """
    started = time.perf_counter()
    chosen = (model or "").strip()
    prompt_tokens = _prompt_tokens(messages)
    required = _required_modalities(messages)
    handler = on_chunk or _chunk_sink.get()

    provider_config = config_service.get_typed(session, "llm_providers", LlmProviderConfig)
    # Before the model check: a vision call with no capable endpoint gets an
    # empty binding, and "no image endpoint" is the message that is true.
    _check_capable(provider_config, preferred_endpoint_ids, required)

    if not chosen:
        raise ProviderTemporaryFailure(f"智能体「{agent_name}」尚未在后台配置模型，无法调用。")

    endpoints = failover.eligible_candidates(
        provider_config, preferred_ids=preferred_endpoint_ids, required_modalities=required
    )
    if not endpoints:
        endpoints = _wait_for_capacity(provider_config, preferred_endpoint_ids, required)

    last_error: Exception | None = None
    tried_endpoint = False

    for endpoint_id, endpoint in endpoints:
        if not endpoint.model:
            continue
        tried_endpoint = True
        budget = endpoint.output_budget(
            max_tokens,
            prompt_tokens=prompt_tokens,
            reasoning_model=reasoning_model,
        )
        with failover.lease(endpoint_id):
            response, _used_budget, error, yielded, thinking = _attempt_endpoint(
                client=client_for_endpoint(endpoint),
                max_retries=MAX_TRANSPORT_RETRIES,
                model=endpoint.model,
                messages=messages,
                budget=budget,
                temperature=temperature,
                expect_json=expect_json,
                endpoint=endpoint,
                prompt_tokens=prompt_tokens,
                on_chunk=handler,
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
                latency_ms=int((time.perf_counter() - started) * 1000),
                endpoint_id=endpoint_id,
                thinking=thinking,
            )
        last_error = error
        if yielded:
            # A chunk already reached the caller — switching endpoints would
            # replay thinking/content the UI has already shown.
            break

    if not tried_endpoint:
        # Nothing in `llm_providers` is available (empty pool, or every
        # candidate is breaker-open/at capacity). There is no env-level
        # endpoint to fall back to any more — an operator has to configure one
        # at `/admin/models`.
        if failover.saturated_candidates(
            provider_config, preferred_ids=preferred_endpoint_ids, required_modalities=required
        ):
            raise ProviderTemporaryFailure("LLM 网关繁忙（并发已满），请稍后重试。")
        raise ProviderTemporaryFailure("未配置任何可用的 LLM 网关端点。")

    reason = type(last_error).__name__ if last_error else "unknown_error"
    raise ProviderTemporaryFailure(f"LLM 网关不可用（智能体「{agent_name}」）: {reason}")


def _wait_for_capacity(
    config: LlmProviderConfig,
    preferred_ids: Sequence[str],
    required_modalities: frozenset[str] = frozenset(),
) -> list[tuple[str, LlmProviderEndpoint]]:
    """Waits up to `CAPACITY_WAIT_SECONDS` for a slot on a healthy endpoint
    that is only busy. Returns at once (empty) when nothing is merely busy —
    an empty pool or open breakers will not heal by waiting here."""
    deadline = time.monotonic() + CAPACITY_WAIT_SECONDS

    def eligible() -> list[tuple[str, LlmProviderEndpoint]]:
        return failover.eligible_candidates(
            config, preferred_ids=preferred_ids, required_modalities=required_modalities
        )

    while failover.saturated_candidates(
        config, preferred_ids=preferred_ids, required_modalities=required_modalities
    ):
        if time.monotonic() >= deadline:
            return []
        time.sleep(random.uniform(*CAPACITY_POLL_SECONDS))
        endpoints = eligible()
        if endpoints:
            return endpoints
    return eligible()


def _attempt_endpoint(
    *,
    client: OpenAI,
    max_retries: int,
    model: str,
    messages: list[LlmMessage],
    budget: int,
    temperature: float,
    expect_json: bool,
    endpoint: LlmProviderEndpoint,
    prompt_tokens: int,
    on_chunk: Callable[[StreamChunk], None] | None = None,
) -> tuple[NormalizedResponse | None, int, Exception | None, bool, str]:
    """One endpoint's full retry loop, isolated so `complete()` can move on to
    the next failover candidate without repeating this logic.

    The fourth value is whether any chunk was already handed to `on_chunk`
    (failover and transport retry must both stop in that case). The fifth
    is the raw reasoning trace collected for the attempt that finished.
    """
    transport_limit = max_retries + 1
    transport_attempt = 0
    compatibility_adjusted = False
    truncation_expanded = False
    last_error: Exception | None = None
    yielded = False
    thinking = ""

    def _emit(chunk: StreamChunk) -> None:
        nonlocal yielded
        if on_chunk and chunk.text:
            yielded = True
            on_chunk(chunk)

    while transport_attempt < transport_limit:
        try:
            raw = _call_gateway(
                client=client,
                model=model,
                messages=messages,
                max_tokens=budget,
                temperature=temperature,
                expect_json=expect_json,
                on_chunk=_emit if on_chunk else None,
                prompt_tokens=prompt_tokens,
            )
            thinking = _thinking_from_raw(raw)
            response = normalize_completion(raw, expect_json=expect_json)

            # A truncated reasoning model produced no usable payload: one retry
            # with a larger budget is cheaper than moving to the next endpoint.
            # The ceiling is this endpoint's declared max_output / remaining
            # context — not a code-wide 32k cap that a 4k model cannot honour.
            # After the caller has seen a chunk, retrying would duplicate it.
            if (
                expect_json
                and response.data is None
                and response.truncated
                and not truncation_expanded
                and not yielded
            ):
                truncation_expanded = True
                budget = endpoint.expand_output_budget(budget, prompt_tokens=prompt_tokens)
                continue

            return response, budget, None, yielded, thinking
        except BadRequestError as exc:
            if yielded:
                last_error = exc
                break
            # A rejected parameter is a capability signal, not an outage.
            if not compatibility_adjusted and capabilities.learn_from_error(model, str(exc)):
                compatibility_adjusted = True
                logger.info("adjusted request shape for %s: %s", model, capabilities.get(model))
                continue
            last_error = exc
            logger.warning("llm gateway rejected request for %s: %s", model, exc)
            break
        except (OpenAIError, TimeoutError, ConnectionError) as exc:
            last_error = exc
            logger.warning(
                "llm gateway transport attempt %s/%s failed for %s: %s",
                transport_attempt + 1,
                transport_limit,
                model,
                exc,
            )
            if yielded:
                break
            transport_attempt += 1

    return None, budget, last_error, yielded, thinking


def call_gateway_once(
    *,
    client: OpenAI,
    model: str,
    messages: list[LlmMessage],
    max_tokens: int,
    temperature: float,
    expect_json: bool,
) -> Any:
    """Send one production-shaped request without failover, retry, or stub.

    Kept non-streaming: the admin "验证有效" ping is a 16-token short
    sentence that must not wait on a reasoning model's think phase.
    """
    return _create_completion(
        client=client,
        model=model,
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
        expect_json=expect_json,
    )


def _completion_kwargs(
    *,
    model: str,
    messages: list[LlmMessage],
    max_tokens: int,
    temperature: float,
    expect_json: bool,
) -> dict[str, Any]:
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

    return kwargs


def _create_completion(
    *,
    client: OpenAI,
    model: str,
    messages: list[LlmMessage],
    max_tokens: int,
    temperature: float,
    expect_json: bool,
) -> Any:
    """Non-streaming `create()` — admin connectivity ping only."""
    return client.chat.completions.create(
        **_completion_kwargs(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            expect_json=expect_json,
        )
    )


def _thinking_from_raw(raw: Any) -> str:
    if not isinstance(raw, dict):
        return ""
    choices = raw.get("choices") or [{}]
    message = (choices[0] if choices else {}).get("message") or {}
    return reasoning_text(message)


def _usage_from_sdk(chunk: Any) -> dict[str, int]:
    usage = getattr(chunk, "usage", None)
    if usage is None:
        return {}
    if isinstance(usage, dict):
        prompt = int(usage.get("prompt_tokens") or 0)
        completion = int(usage.get("completion_tokens") or 0)
    else:
        prompt = int(getattr(usage, "prompt_tokens", 0) or 0)
        completion = int(getattr(usage, "completion_tokens", 0) or 0)
    if not prompt and not completion:
        return {}
    return {"prompt_tokens": prompt, "completion_tokens": completion}


def _is_stream_usage_rejection(exc: BadRequestError) -> bool:
    text = str(exc).lower()
    return "stream_options" in text or "include_usage" in text


def _call_gateway(
    *,
    client: OpenAI,
    model: str,
    messages: list[LlmMessage],
    max_tokens: int,
    temperature: float,
    expect_json: bool,
    on_chunk: Callable[[StreamChunk], None] | None = None,
    prompt_tokens: int = 0,
) -> Any:
    """Assembles one completion by draining `_stream_gateway`.

    `timeout_ms` on the cached client only bounds idle gaps between bytes;
    thinking deltas reset that idle timer. The wall-clock ceiling is
    `STREAM_WALL_CLOCK_TIMEOUT_SECONDS`, checked once per delta.
    """
    started = time.perf_counter()
    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    finish_reason = "stop"
    usage: dict[str, int] = {}
    include_usage = True

    def consume() -> None:
        nonlocal finish_reason, usage
        for delta in _stream_gateway(
            client=client,
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            expect_json=expect_json,
            include_usage=include_usage,
        ):
            if time.perf_counter() - started > STREAM_WALL_CLOCK_TIMEOUT_SECONDS:
                raise TimeoutError(
                    f"stream exceeded {STREAM_WALL_CLOCK_TIMEOUT_SECONDS}s wall clock"
                )
            if delta.reasoning:
                reasoning_parts.append(delta.reasoning)
                if on_chunk:
                    on_chunk(StreamChunk(kind="thinking", text=delta.reasoning))
            if delta.content:
                content_parts.append(delta.content)
                if on_chunk:
                    on_chunk(StreamChunk(kind="content", text=delta.content))
            if delta.finish_reason:
                finish_reason = delta.finish_reason
            if delta.usage:
                usage = delta.usage

    try:
        consume()
    except BadRequestError as exc:
        if (
            include_usage
            and _is_stream_usage_rejection(exc)
            and not (content_parts or reasoning_parts)
        ):
            include_usage = False
            consume()
        else:
            raise

    if not usage:
        usage = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": len("".join(content_parts)) // 4,
        }

    return {
        "model": model,
        "choices": [
            {
                "message": {
                    "content": "".join(content_parts),
                    "reasoning_content": "".join(reasoning_parts),
                },
                "finish_reason": finish_reason,
            }
        ],
        "usage": usage,
    }


def stream_complete(
    *,
    session: Session,
    agent_name: str,
    model: str,
    messages: list[LlmMessage],
    result: StreamResult,
    max_tokens: int = 2048,
    temperature: float = 0.4,
    reasoning_model: bool = False,
    preferred_endpoint_ids: Sequence[str] = (),
    is_usable: Callable[[str], bool] | None = None,
    expect_json: bool = False,
    retry_nudge: str | None = None,
) -> Iterator[StreamChunk]:
    """Streams typed chunks for one agent turn, filling `result` as it goes.

    This is a separate path from `complete()`, not a mode of it: JSON-mode
    responses are parsed as one blob (`normalize_completion`), but a
    streaming turn is plain/mixed text handed to the caller token-by-token,
    so there is nothing to normalize until the generator is exhausted.

    `expect_json` is forwarded to `_stream_gateway` so a JSON-only slot
    (prompt polish) can ask for `response_format=json_object` the same way
    `complete()` does. Script writing stays `False` — its contract is mixed
    prose plus a fenced JSON block.

    Resolves the endpoint list against `session` *before* returning the
    iterator, so a caller can close that session and still drain the stream
    (script writing holds a DB connection for the LLM call otherwise).

    Reasoning models are handled the same way as `complete()` for budgeting
    (endpoint's declared `max_output_tokens` / remaining `context_length`,
    see `LlmProviderEndpoint.output_budget`), but *not* for what happens to
    the reasoning text itself: every reasoning delta is yielded live as a
    `kind="thinking"` chunk (unlike the old contract, which only recovered it
    after the stream ended and never surfaced it to the caller) — a reasoning
    model "thinking out loud" is now part of the visible creation process,
    not a network-layer implementation detail. Recovery still happens the
    same way once the stream ends: an empty `content` pass falls back to
    `strip_thinking`-cleaned reasoning for `result.text` (the
    glm-5.3-flash case, where the answer itself ended up in the reasoning
    channel), and a pass with neither — or a thinking-only pass that hits
    the wall-clock / transport timeout before JSON arrives — is retried
    once with a larger budget capped by those same fields. A retry that
    still produces no visible text leaves `result.text` empty so the
    caller can surface `parse_ok=False` rather than wrapping the timeout
    as a gateway outage (thinking already reached the UI). `result.thinking`
    always holds the raw reasoning text collected for the attempt that
    finished the call, regardless of whether it was also used to recover
    `result.text`.

    `is_usable`, when given, gates that same retry decision one step
    further: recovered thinking, or content that already reached the UI but
    still fails the check (truncated / decoy JSON), is treated as empty for
    one same-endpoint retry. Mid-stream failover to another endpoint is
    still forbidden. `retry_nudge`, when given, is appended as a user turn
    on that retry so a reasoning model that spent the first budget thinking
    is told to emit the payload now. Prose thinking that never resolves
    into anything the caller can use must not masquerade as `result.text`.

    Deliberately no mid-stream failover: once a chunk has been yielded from
    an endpoint, that endpoint is used for the rest of the turn even if it
    later errors, because a chat bubble that is already mid-sentence cannot
    silently restart on a different provider without a visibly broken UI. A
    connection that fails before yielding anything still moves on to the
    next candidate, same as `complete()`.

    Input-modality routing and `NoCapableEndpoint` work as in `complete()`.

    Raises `ProviderTemporaryFailure` under the same conditions `complete()`
    does — no model bound, no endpoint configured, or every candidate failed
    before yielding anything — rather than ever yielding fabricated text.
    """
    started = time.perf_counter()
    chosen = (model or "").strip()
    prompt_tokens = _prompt_tokens(messages)
    required = _required_modalities(messages)

    provider_config = config_service.get_typed(session, "llm_providers", LlmProviderConfig)
    _check_capable(provider_config, preferred_endpoint_ids, required)

    if not chosen:
        raise ProviderTemporaryFailure(f"智能体「{agent_name}」尚未在后台配置模型，无法调用。")

    endpoints = [
        (endpoint_id, endpoint)
        for endpoint_id, endpoint in failover.eligible_candidates(
            provider_config, preferred_ids=preferred_endpoint_ids, required_modalities=required
        )
        if endpoint.model
    ]
    if not endpoints:
        raise ProviderTemporaryFailure("未配置任何可用的 LLM 网关端点。")

    return _stream_complete_from_endpoints(
        endpoints=endpoints,
        messages=messages,
        result=result,
        requested=max_tokens,
        reasoning_model=reasoning_model,
        temperature=temperature,
        started=started,
        chosen=chosen,
        prompt_tokens=prompt_tokens,
        agent_name=agent_name,
        is_usable=is_usable,
        expect_json=expect_json,
        retry_nudge=retry_nudge,
    )


def _stream_complete_from_endpoints(
    *,
    endpoints: list[tuple[str, LlmProviderEndpoint]],
    messages: list[LlmMessage],
    result: StreamResult,
    requested: int,
    reasoning_model: bool,
    temperature: float,
    started: float,
    chosen: str,
    prompt_tokens: int,
    agent_name: str,
    is_usable: Callable[[str], bool] | None = None,
    expect_json: bool = False,
    retry_nudge: str | None = None,
) -> Iterator[StreamChunk]:
    """The session-free half of `stream_complete` — endpoint list is already
    resolved, so the caller's DbSession can close before this generator runs."""

    def _finalize(
        *, text: str, endpoint_id: str, thinking: str, served_model: str | None = None
    ) -> None:
        result.text = text
        result.thinking = thinking
        result.endpoint_id = endpoint_id
        result.model = served_model or chosen
        result.prompt_tokens = prompt_tokens
        result.completion_tokens = len(text) // 4
        result.latency_ms = int((time.perf_counter() - started) * 1000)

    last_error: Exception | None = None

    for endpoint_id, endpoint in endpoints:
        client = client_for_endpoint(endpoint)
        attempt_budget = endpoint.output_budget(
            requested,
            prompt_tokens=prompt_tokens,
            reasoning_model=reasoning_model,
        )
        truncation_expanded = False
        yielded_from_endpoint = False
        streamed_any = False
        attempt_messages = messages
        while True:
            accumulated: list[str] = []
            reasoning_parts: list[str] = []
            error: Exception | None = None
            attempt_started = time.perf_counter()
            with failover.lease(endpoint_id):
                try:
                    for delta in _stream_gateway(
                        client=client,
                        model=endpoint.model,
                        messages=attempt_messages,
                        max_tokens=attempt_budget,
                        temperature=temperature,
                        expect_json=expect_json,
                    ):
                        if delta.reasoning:
                            reasoning_parts.append(delta.reasoning)
                            streamed_any = True
                            yield StreamChunk(kind="thinking", text=delta.reasoning)
                        if delta.content:
                            accumulated.append(delta.content)
                            yielded_from_endpoint = True
                            streamed_any = True
                            yield StreamChunk(kind="content", text=delta.content)
                        if (
                            time.perf_counter() - attempt_started
                            > STREAM_WALL_CLOCK_TIMEOUT_SECONDS
                        ):
                            raise TimeoutError(
                                f"stream exceeded {STREAM_WALL_CLOCK_TIMEOUT_SECONDS}s wall clock"
                            )
                except (OpenAIError, TimeoutError, ConnectionError) as exc:
                    error = exc
                    logger.warning(
                        "llm gateway stream failed for %s (endpoint=%s): %s",
                        endpoint.model,
                        endpoint_id,
                        exc,
                    )

            visible = "".join(accumulated)
            thinking = "".join(reasoning_parts)
            if not visible and reasoning_parts:
                recovered = strip_thinking(thinking)
                if recovered:
                    visible = recovered
                elif "{" in thinking:
                    # An unterminated `<think>` would otherwise wipe a JSON
                    # payload that only ever lived inside the reasoning
                    # channel — keep the raw trace for `is_usable`.
                    visible = thinking

            # Retry when nothing usable survived recovery — either nothing
            # came back at all, or (when the caller cares, e.g. a script
            # parser / enhance JSON shape) what arrived still isn't
            # something it can use. A reasoning-only pass with
            # `finish_reason=length` whose recovered text *is* usable is
            # the glm-5.3-flash success case: the answer is in `visible`
            # after `strip_thinking`, and a second attempt would wipe it.
            #
            # A wall-clock / transport timeout mid-think used to skip this
            # retry (`error is not None`) and surface as "LLM 网关不可用:
            # TimeoutError" even though thinking had already reached the UI.
            # Same-endpoint budget expansion is still allowed; mid-stream
            # failover to another endpoint is not. Unusable *content* (a
            # decoy object, or JSON cut off mid-object) also gets that one
            # retry — the polish UI only commits on `complete`, so a second
            # same-endpoint attempt does not rewrite a bubble mid-sentence.
            recovered_unusable = bool(visible and is_usable is not None and not is_usable(visible))
            transport_retryable = error is None or isinstance(error, (TimeoutError, OpenAIError))
            should_retry = (
                transport_retryable
                and not truncation_expanded
                and (not yielded_from_endpoint or recovered_unusable)
                and (not visible or recovered_unusable)
            )
            if should_retry:
                truncation_expanded = True
                attempt_budget = endpoint.expand_output_budget(
                    attempt_budget, prompt_tokens=prompt_tokens
                )
                if retry_nudge:
                    attempt_messages = [*messages, {"role": "user", "content": retry_nudge}]
                continue

            if recovered_unusable:
                # The one retry is already spent and the recovered reasoning
                # text still isn't something the caller can use (e.g. no
                # parseable script JSON) — don't let it masquerade as a
                # successful `result.text`. Treat it the same as no visible
                # text at all so the caller can surface `parse_ok=False`.
                visible = ""

            if accumulated or visible or error is None or streamed_any:
                failover.record_outcome(
                    endpoint_id,
                    success=True,
                    failure_threshold=CIRCUIT_BREAKER_FAILURE_THRESHOLD,
                    cooldown_s=CIRCUIT_BREAKER_COOLDOWN_SECONDS,
                )
                _finalize(
                    text=visible,
                    endpoint_id=endpoint_id,
                    thinking=thinking,
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
            break

    reason = type(last_error).__name__ if last_error else "unknown_error"
    raise ProviderTemporaryFailure(f"LLM 网关不可用（智能体「{agent_name}」）: {reason}")


def _stream_gateway(
    *,
    client: OpenAI,
    model: str,
    messages: list[LlmMessage],
    max_tokens: int,
    temperature: float,
    expect_json: bool = False,
    include_usage: bool = False,
) -> Iterator[StreamDelta]:
    """One streamed request, no retry/failover — `stream_complete` / `_call_gateway` own that.

    Yields `StreamDelta` so reasoning tokens and `finish_reason` survive
    even when `delta.content` is empty (the glm-5.3-flash failure mode).
    A usage-only trailing chunk (empty `choices`, `stream_options.include_usage`)
    is yielded as `StreamDelta(usage=...)`.
    """
    kwargs = _completion_kwargs(
        model=model,
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
        expect_json=expect_json,
    )
    kwargs["stream"] = True
    if include_usage:
        kwargs["stream_options"] = {"include_usage": True}

    stream = client.chat.completions.create(**kwargs)
    for chunk in stream:
        usage = _usage_from_sdk(chunk)
        if not chunk.choices:
            if usage:
                yield StreamDelta(usage=usage)
            continue
        choice = chunk.choices[0]
        delta = choice.delta
        content = (getattr(delta, "content", None) or "") if delta is not None else ""
        if not isinstance(content, str):
            content = str(content)
        finish = getattr(choice, "finish_reason", None) or ""
        yield StreamDelta(
            content=content,
            reasoning=reasoning_text_from_delta(delta),
            finish_reason=str(finish) if finish else "",
            usage=usage or None,
        )


def probe(session: Session) -> dict[str, Any]:
    """Connectivity check for the ops console health panel.

    Picks the "general" primary endpoint if one exists, otherwise any enabled
    endpoint — there is no env-level endpoint to fall back to any more.
    """
    provider_config = config_service.get_typed(session, "llm_providers", LlmProviderConfig)
    candidates = failover.general_candidates(provider_config)
    if not candidates:
        return {"reachable": False, "detail": "未配置任何网关端点"}
    _endpoint_id, endpoint = candidates[0]

    started = time.perf_counter()
    try:
        models = client_for_endpoint(endpoint).models.list()
        count = len(getattr(models, "data", []) or [])
        return {
            "reachable": True,
            "model_count": count,
            "latency_ms": int((time.perf_counter() - started) * 1000),
        }
    except Exception as exc:
        return {"reachable": False, "detail": type(exc).__name__}
