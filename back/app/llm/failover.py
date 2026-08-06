"""Concurrency- and health-aware endpoint selection for the LLM gateway.

Deliberately independent of `app/agents/router.py`: that module scores
image/video *generation* providers with an explainable weighted formula.
This module picks which OpenAI-compatible *LLM* endpoint an agent call goes
out on. There is no scoring here — just priority order, a live concurrency
lease, and a circuit breaker — because the point is fast, boring failover
between interchangeable endpoints, not quality/cost trade-offs.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Iterator
from dataclasses import dataclass

import redis

from app.api.rate_limit import get_redis
from app.platform_config.schemas import LlmProviderConfig, LlmProviderEndpoint

logger = logging.getLogger(__name__)

_CONCURRENCY_PREFIX = "llmfo:conc:"
_BREAKER_PREFIX = "llmfo:brk:"
_STATS_PREFIX = "llmfo:stats:"

# Backstop only: `lease()` decrements on its own in the normal path. This just
# guarantees a slot is not leaked forever if a worker process dies mid-call.
_CONCURRENCY_LEASE_TTL_SECONDS = 120
# Window for the "recent success rate" shown in the admin console. Independent
# of the breaker's own failure-streak counter, which resets on any success.
_STATS_WINDOW_SECONDS = 3600


def general_candidates(config: LlmProviderConfig) -> list[tuple[str, LlmProviderEndpoint]]:
    """Enabled `kind="general"` endpoints: the primary first, then backups in
    `backup_order`.

    Every agent role (safety/planner/quality/copy) draws from this single
    shared pool — there is no per-role scenario tag any more.
    """
    matches = [
        (endpoint_id, endpoint)
        for endpoint_id, endpoint in config.endpoints.items()
        if endpoint.enabled and endpoint.kind == "general"
    ]
    matches.sort(key=lambda pair: _role_sort_key(pair[1], pair[0]))
    return matches


def _role_sort_key(endpoint: LlmProviderEndpoint, endpoint_id: str) -> tuple[int, int, str]:
    is_backup = endpoint.role == "backup"
    return (int(is_backup), endpoint.backup_order if is_backup else 0, endpoint_id)


def eligible_candidates(config: LlmProviderConfig) -> list[tuple[str, LlmProviderEndpoint]]:
    """Candidates with a free concurrency slot and a closed circuit breaker.

    `client.complete()` walks this list in order, trying the next endpoint on
    failure — the list is the fallback order, not just the top pick.
    """
    client = get_redis()
    ordered = general_candidates(config)
    return [
        (endpoint_id, endpoint)
        for endpoint_id, endpoint in ordered
        if not is_breaker_open(client, endpoint_id)
        and current_concurrency(client, endpoint_id) < endpoint.max_concurrency
    ]


def is_breaker_open(client: redis.Redis, endpoint_id: str) -> bool:
    try:
        return bool(client.exists(f"{_BREAKER_PREFIX}{endpoint_id}:open"))
    except redis.RedisError:
        # Availability beats strictness: a Redis outage must not take every
        # endpoint out of rotation.
        return False


def current_concurrency(client: redis.Redis, endpoint_id: str) -> int:
    try:
        raw = client.get(f"{_CONCURRENCY_PREFIX}{endpoint_id}")
        return int(raw) if raw else 0
    except redis.RedisError:
        return 0


@contextlib.contextmanager
def lease(endpoint_id: str) -> Iterator[None]:
    """Holds one concurrency slot on `endpoint_id` for the call's duration."""
    client = get_redis()
    key = f"{_CONCURRENCY_PREFIX}{endpoint_id}"
    try:
        client.incr(key)
        client.expire(key, _CONCURRENCY_LEASE_TTL_SECONDS)
    except redis.RedisError:
        logger.warning("failed to acquire llm endpoint lease for %s", endpoint_id)
    try:
        yield
    finally:
        with contextlib.suppress(redis.RedisError):
            if int(client.decr(key)) < 0:
                client.set(key, 0)


def record_outcome(
    endpoint_id: str,
    *,
    success: bool,
    failure_threshold: int,
    cooldown_s: int,
) -> None:
    """Updates both the breaker's failure streak and the display-only stats window."""
    client = get_redis()
    fail_key = f"{_BREAKER_PREFIX}{endpoint_id}:fails"
    try:
        if success:
            client.delete(fail_key)
        else:
            fails = client.incr(fail_key)
            client.expire(fail_key, cooldown_s)
            if fails >= failure_threshold:
                client.setex(f"{_BREAKER_PREFIX}{endpoint_id}:open", cooldown_s, "1")
    except redis.RedisError:
        logger.warning("failed to update circuit breaker state for %s", endpoint_id)

    stats_key = f"{_STATS_PREFIX}{endpoint_id}:{'ok' if success else 'fail'}"
    with contextlib.suppress(redis.RedisError):
        client.incr(stats_key)
        client.expire(stats_key, _STATS_WINDOW_SECONDS)


@dataclass(slots=True, frozen=True)
class EndpointRuntimeStatus:
    concurrency_in_use: int
    circuit_breaker_open: bool
    recent_attempts: int
    recent_success_rate: float | None


def runtime_status(endpoint_id: str) -> EndpointRuntimeStatus:
    """Snapshot for the admin console: occupancy, breaker state, recent success rate."""
    client = get_redis()
    successes = _safe_int(client, f"{_STATS_PREFIX}{endpoint_id}:ok")
    failures = _safe_int(client, f"{_STATS_PREFIX}{endpoint_id}:fail")
    total = successes + failures
    return EndpointRuntimeStatus(
        concurrency_in_use=current_concurrency(client, endpoint_id),
        circuit_breaker_open=is_breaker_open(client, endpoint_id),
        recent_attempts=total,
        recent_success_rate=(successes / total) if total > 0 else None,
    )


def _safe_int(client: redis.Redis, key: str) -> int:
    try:
        raw = client.get(key)
        return int(raw) if raw else 0
    except redis.RedisError:
        return 0
