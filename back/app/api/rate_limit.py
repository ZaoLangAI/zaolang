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

        try:
            pipe = self.client.pipeline()
            pipe.zremrangebyscore(key, 0, now_ms - window_ms)
            # The member must be unique per call. Keying it on the timestamp
            # alone would let a burst inside one millisecond overwrite itself
            # and count as a single request — exactly the burst worth catching.
            pipe.zadd(key, {f"{now_ms}-{uuid.uuid4().hex}": now_ms})
            pipe.zcard(key)
            pipe.expire(key, rule.window_seconds + 1)
            _, _, count, _ = pipe.execute()
        except redis.RedisError:
            # Availability beats strictness: a Redis outage must not lock every
            # user out of the product.
            return

        if int(count) > rule.limit:
            retry_after = rule.window_seconds
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
