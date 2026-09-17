"""Per-user cap on concurrent long-lived SSE connections.

Without this, opening the same job/notification stream from several tabs (or
leaving stale tabs open) has no ceiling: each connection holds a request
thread/coroutine and a Redis pub/sub subscription for up to
`SSE_MAX_DURATION_SECONDS`, and enough of them can starve a uvicorn worker's
concurrency budget the same way an unbounded queue would.

Backed by Redis (like `app.api.rate_limit`) rather than an in-process
counter, so the cap holds across every worker process, not just one. A
sorted set doubles as self-healing membership: each active stream is a
member scored by its own last-refresh time, and a stream that stops
refreshing (crashed process, killed connection that never reached `finally`)
ages out of the count within `STALE_AFTER_SECONDS` on its own — no
decrement-on-disconnect to rely on.
"""

from __future__ import annotations

import contextlib
import time
import uuid

import redis

from app.api.rate_limit import get_redis
from app.domain.errors import RateLimited

# Comfortably above every caller's own heartbeat interval (15s for both
# `jobs.stream_events` and `community.stream_notifications`) so a slow tick
# under normal load is never mistaken for a dead connection.
STALE_AFTER_SECONDS = 45

# A handful of legitimate tabs/tools per user, not a hard architectural
# limit — sized to catch "forgot to close 20 tabs" / a runaway client retry
# loop, not to constrain normal multi-tasking.
MAX_CONCURRENT_STREAMS_PER_USER = 8


def reserve(scope: str, user_id: str) -> str:
    """Claims one of `user_id`'s concurrent-stream slots for `scope`
    (e.g. `"job_events"`, `"notifications"`) before a `StreamingResponse` is
    constructed — streaming can't change its status code after the first
    byte, so the check must happen here, not inside the generator.

    Returns the member token the generator must pass to `touch`/`release`.
    Raises `RateLimited` if the user is already at the cap. Fails open on a
    Redis outage, matching `rate_limit.RateLimiter`'s availability-first policy.
    """
    key = _key(scope, user_id)
    member = uuid.uuid4().hex
    client = get_redis()
    now = time.time()

    try:
        pipe = client.pipeline()
        pipe.zremrangebyscore(key, 0, now - STALE_AFTER_SECONDS)
        pipe.zcard(key)
        _, count = pipe.execute()
    except redis.RedisError:
        return member

    if int(count) >= MAX_CONCURRENT_STREAMS_PER_USER:
        raise RateLimited(
            "同时打开的实时连接过多，请关闭部分页面或任务后重试。", retry_after_seconds=5
        )

    with contextlib.suppress(redis.RedisError):
        pipe = client.pipeline()
        pipe.zadd(key, {member: now})
        pipe.expire(key, STALE_AFTER_SECONDS)
        pipe.execute()
    return member


def touch(scope: str, user_id: str, member: str) -> None:
    """Refreshes a claimed slot. Must be called at least once per
    `STALE_AFTER_SECONDS` from inside the generator's own heartbeat loop, or
    the slot ages out from under a connection that is still open."""
    with contextlib.suppress(redis.RedisError):
        client = get_redis()
        pipe = client.pipeline()
        pipe.zadd(_key(scope, user_id), {member: time.time()})
        pipe.expire(_key(scope, user_id), STALE_AFTER_SECONDS)
        pipe.execute()


def release(scope: str, user_id: str, member: str) -> None:
    """Frees a slot early. Best-effort: if this never runs (worker killed
    mid-stream), the slot still self-heals via `STALE_AFTER_SECONDS`."""
    with contextlib.suppress(redis.RedisError):
        get_redis().zrem(_key(scope, user_id), member)


def _key(scope: str, user_id: str) -> str:
    return f"sse:{scope}:{user_id}"
