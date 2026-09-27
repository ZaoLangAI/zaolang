"""Layered rate limiting.

Buckets are tiered by cost, not by endpoint count: an anonymous read is cheap,
a login attempt is sensitive, and a generation submission is expensive. Limits
are enforced in Redis with a sliding window so a burst at a window boundary
cannot double the allowance.
"""

from __future__ import annotations

import contextlib
import time
import uuid
from dataclasses import dataclass
from functools import lru_cache

import redis

from app.config import get_settings
from app.domain.errors import RateLimited


@dataclass(frozen=True, slots=True)
class RateLimitRule:
    limit: int
    window_seconds: int


RULES: dict[str, RateLimitRule] = {
    "public_read": RateLimitRule(limit=240, window_seconds=60),
    "authenticated_write": RateLimitRule(limit=90, window_seconds=60),
    "auth_attempt": RateLimitRule(limit=10, window_seconds=300),
    "generation_submit": RateLimitRule(limit=12, window_seconds=60),
    "upload_presign": RateLimitRule(limit=30, window_seconds=60),
    "editor_write": RateLimitRule(limit=60, window_seconds=60),
    "editor_export": RateLimitRule(limit=20, window_seconds=60),
    # Each call is a real LLM turn (draft or revise), not a cheap metadata
    # write — priced between `editor_write` and the much stricter
    # `generation_submit`.
    "script_studio_write": RateLimitRule(limit=20, window_seconds=60),
    # A real platform push per channel (upload + create_post) — heavier than
    # `authenticated_write`, lighter than `generation_submit`'s per-provider cost.
    "platform_publish": RateLimitRule(limit=20, window_seconds=60),
    # Inviting a co-creator pushes a notification to a stranger — sensitive
    # in the same way a login attempt is, so it gets its own strict budget
    # rather than sharing `editor_write`'s much looser one.
    "series_collab_invite": RateLimitRule(limit=10, window_seconds=300),
    # Following notifies a stranger (and an unfollow/re-follow cycle notifies
    # again); a report lands in the operator queue with no dedupe. Both are
    # cheap to send and costly to receive, so neither shares
    # `authenticated_write`'s budget.
    "social_outreach": RateLimitRule(limit=30, window_seconds=300),
    "mcp_tool": RateLimitRule(limit=60, window_seconds=60),
    # Back office gets its own budget so consumer traffic can never starve an
    # operator during an incident.
    "admin_read": RateLimitRule(limit=300, window_seconds=60),
    "admin_write": RateLimitRule(limit=60, window_seconds=60),
    "admin_dangerous": RateLimitRule(limit=10, window_seconds=300),
}


@lru_cache
def get_redis() -> redis.Redis:
    return redis.Redis.from_url(get_settings().redis_url, decode_responses=True)


class RateLimiter:
    def __init__(self, client: redis.Redis | None = None) -> None:
        self._client = client

    @property
    def client(self) -> redis.Redis:
        return self._client or get_redis()

    def check(self, bucket: str, identity: str) -> None:
        rule = RULES[bucket]
        key = f"rl:{bucket}:{identity}"
        now_ms = int(time.time() * 1000)
        window_ms = rule.window_seconds * 1000
        ttl = rule.window_seconds + 1

        try:
            pipe = self.client.pipeline()
            pipe.zremrangebyscore(key, 0, now_ms - window_ms)
            pipe.zcard(key)
            _, count = pipe.execute()
        except redis.RedisError:
            # Availability beats strictness: a Redis outage must not lock every
            # user out of the product.
            return

        # Check before adding: a caller already at the limit must not still
        # write a member. Otherwise sustained abusive traffic makes this set
        # grow with the request rate instead of staying bounded near `limit`.
        already_over = int(count) >= rule.limit
        if already_over:
            with contextlib.suppress(redis.RedisError):
                self.client.expire(key, ttl)
        else:
            try:
                pipe = self.client.pipeline()
                # The member must be unique per call. Keying it on the
                # timestamp alone would let a burst inside one millisecond
                # overwrite itself and count as a single request — exactly
                # the burst worth catching.
                pipe.zadd(key, {f"{now_ms}-{uuid.uuid4().hex}": now_ms})
                pipe.expire(key, ttl)
                pipe.execute()
            except redis.RedisError:
                return

        if already_over:
            retry_after = rule.window_seconds
            # Local import: `system_log` reuses `get_redis` from this module,
            # so importing it at module scope would be circular.
            from app.domain.system_log import service as system_log
            from app.models.enums import SystemLogLevel, SystemLogSource

            system_log.emit(
                source=SystemLogSource.RATE_LIMIT,
                event=f"rate_limited.{bucket}",
                level=SystemLogLevel.WARNING,
                message=f"{identity} 触发限流桶 {bucket}（{int(count)}/{rule.limit}）。",
                dedup_key=f"{bucket}:{identity}",
                window_seconds=rule.window_seconds,
                details={"bucket": bucket, "identity": identity, "count": int(count)},
            )
            raise RateLimited(
                f"操作过于频繁，请在 {retry_after} 秒后重试。", retry_after_seconds=retry_after
            )

    def reset(self, bucket: str, identity: str) -> None:
        with contextlib.suppress(redis.RedisError):
            self.client.delete(f"rl:{bucket}:{identity}")


_limiter = RateLimiter()


def enforce(bucket: str, identity: str) -> None:
    _limiter.check(bucket, identity)


def reset(bucket: str, identity: str) -> None:
    _limiter.reset(bucket, identity)
