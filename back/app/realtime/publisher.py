"""Redis pub/sub bridge for job progress.

Pub/sub only carries the live tail. The durable record is `JobEvent` in
Postgres, and a reconnecting client backfills from there using `Last-Event-ID`,
so a dropped message is never lost — only delayed until the next poll.
"""

from __future__ import annotations

import contextlib
import json
import logging
from collections.abc import Iterator
from typing import Any

import redis

from app.api.rate_limit import get_redis

logger = logging.getLogger(__name__)

CHANNEL_PREFIX = "job-events:"
SUBSCRIBE_TIMEOUT_SECONDS = 1.0


def channel_for(job_id: str) -> str:
    return f"{CHANNEL_PREFIX}{job_id}"


def publish_job_event(job_id: str, payload: dict[str, Any]) -> None:
    try:
        get_redis().publish(channel_for(job_id), json.dumps(payload, ensure_ascii=False))
    except redis.RedisError:
        # Delivery is best-effort by design; the database remains authoritative.
        logger.warning("could not publish event for job %s", job_id)


def subscribe(job_id: str) -> Iterator[dict[str, Any]]:
    """Yields live events until the caller stops consuming."""
    pubsub = get_redis().pubsub(ignore_subscribe_messages=True)
    pubsub.subscribe(channel_for(job_id))
    try:
        while True:
            message = pubsub.get_message(timeout=SUBSCRIBE_TIMEOUT_SECONDS)
            if message is None:
                yield {}  # Heartbeat slot; keeps the SSE connection warm.
                continue
            data = message.get("data")
            if not data:
                continue
            try:
                yield json.loads(data)
            except json.JSONDecodeError:
                continue
    finally:
        with contextlib.suppress(redis.RedisError):
            pubsub.close()
