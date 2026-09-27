"""Cross-job circuit breaker for media generation routes.

`router.route()` already excludes a provider that failed *earlier in the same
job* (`previously_failed_this_job`). This is the cross-job complement: a route
that keeps failing for everyone is taken out of rotation for a cooldown, so a
brand-new job's first attempt does not walk straight into it.

It is a hard filter, never a score (see the `zaolang-agent-gateway` skill on
the media circuit breaker and on routing: filtering is code, choosing is the
LLM's):
`route()` marks an open route `filter_reason="provider_circuit_open"` like any
other ineligible candidate, and the LLM selector never sees breaker state.
Same Redis shape as the LLM gateway's breaker (`app/llm/failover.py`) under
its own prefix — the two select different things and must not share keys.

Lifecycle, per route (the catalogue key `"{endpoint_id}:{tag}"`):
- closed: counted failures accumulate in a short window;
- open: `FAILURE_THRESHOLD` of them trip it for `COOLDOWN_SECONDS`;
- half-open: after the cooldown exactly one probe is let through (a `SET NX`
  lock); a success closes the breaker, a failed probe re-opens it at once.

A Redis outage fails open (every route stays eligible): availability beats
strictness, exactly as for the LLM breaker.
"""

from __future__ import annotations

import logging

import redis

from app.api.rate_limit import get_redis

logger = logging.getLogger(__name__)

KEY_PREFIX = "mediafo:brk:"
FAILURE_THRESHOLD = 5
COOLDOWN_SECONDS = 120
# How long a half-open probe holds its slot before another may try.
PROBE_LOCK_SECONDS = 60
# How long a tripped route stays "half-open" (awaiting a successful probe)
# before the breaker forgets it entirely.
HALF_OPEN_MEMORY_SECONDS = COOLDOWN_SECONDS * 30

# Only failures that say something about the route itself. A missing or
# rejected *input*, a user cancel, or a quality rejection is not the
# provider's fault and must not take it out of rotation for everyone.
COUNTED_FAILURE_CODES = frozenset(
    {
        "PROVIDER_TEMPORARY_FAILURE",
        "PROVIDER_INVALID_RESPONSE",
        "PROVIDER_TASK_FAILED",
        "PROVIDER_TIMEOUT",
    }
)


def _keys(provider: str) -> tuple[str, str, str, str]:
    base = f"{KEY_PREFIX}{provider}"
    return f"{base}:fails", f"{base}:open", f"{base}:half", f"{base}:probe"


def is_open(provider: str) -> bool:
    """Whether `route()` must filter this route out right now.

    During the half-open window the first caller claims the probe slot and is
    let through; everyone else keeps seeing it open until that probe resolves
    (or its lock lapses, which lets the next caller probe).
    """
    _, open_key, half_key, probe_key = _keys(provider)
    try:
        client = get_redis()
        if client.exists(open_key):
            return True
        if client.exists(half_key):
            claimed = client.set(probe_key, "1", nx=True, ex=PROBE_LOCK_SECONDS)
            return not claimed
        return False
    except redis.RedisError:
        return False


def record_outcome(provider: str, *, success: bool, failure_code: str | None = None) -> None:
    """Feeds one finished provider attempt into the breaker."""
    fails_key, open_key, half_key, probe_key = _keys(provider)
    try:
        client = get_redis()
        if success:
            client.delete(fails_key, half_key, probe_key)
            return
        if (failure_code or "PROVIDER_TEMPORARY_FAILURE") not in COUNTED_FAILURE_CODES:
            return
        if client.exists(half_key):
            # A failed half-open probe: the route is still broken.
            _trip(client, fails_key, open_key, half_key, probe_key)
            return
        fails = int(client.incr(fails_key))
        client.expire(fails_key, COOLDOWN_SECONDS)
        if fails >= FAILURE_THRESHOLD:
            _trip(client, fails_key, open_key, half_key, probe_key)
    except redis.RedisError:
        logger.warning("failed to update media circuit breaker state for %s", provider)


def _trip(
    client: redis.Redis, fails_key: str, open_key: str, half_key: str, probe_key: str
) -> None:
    client.setex(open_key, COOLDOWN_SECONDS, "1")
    client.set(half_key, "1", ex=HALF_OPEN_MEMORY_SECONDS)
    client.delete(fails_key, probe_key)
    logger.warning("media route circuit breaker opened: %s", open_key)


def open_routes_for_endpoint(endpoint_id: str) -> list[str]:
    """Routes of one configured endpoint that are cooling down right now —
    what the admin console shows next to that endpoint."""
    pattern = f"{KEY_PREFIX}{endpoint_id}:*:open"
    try:
        client = get_redis()
        return sorted(
            str(key.decode() if isinstance(key, bytes) else key)
            .removeprefix(KEY_PREFIX)
            .removesuffix(":open")
            for key in client.scan_iter(match=pattern, count=200)
        )
    except redis.RedisError:
        return []
