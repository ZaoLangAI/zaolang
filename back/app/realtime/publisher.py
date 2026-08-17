"""Redis pub/sub bridge for job progress and user notifications.

Pub/sub only carries the live tail. For job progress the durable record is
`JobEvent` in Postgres, and a reconnecting client backfills from there using
`Last-Event-ID`, so a dropped message is never lost — only delayed until the
next poll. For notifications the durable record is the `Notification` row
itself, polled via `GET /v1/notifications`; the stream here is a live-update
convenience on top of that, not the source of truth.
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
NOTIFICATION_CHANNEL_PREFIX = "notifications:"
SUBSCRIBE_TIMEOUT_SECONDS = 1.0


def channel_for(job_id: str) -> str:
    return f"{CHANNEL_PREFIX}{job_id}"


def channel_for_user(user_id: str) -> str:
    return f"{NOTIFICATION_CHANNEL_PREFIX}{user_id}"


def publish_job_event(job_id: str, payload: dict[str, Any]) -> None:
    try:
        get_redis().publish(channel_for(job_id), json.dumps(payload, ensure_ascii=False))
    except redis.RedisError:
        # Delivery is best-effort by design; the database remains authoritative.
        logger.warning("could not publish event for job %s", job_id)


def publish_notification(user_id: str, payload: dict[str, Any]) -> None:
    try:
        get_redis().publish(channel_for_user(user_id), json.dumps(payload, ensure_ascii=False))
    except redis.RedisError:
        # Best-effort, same as publish_job_event: the Notification row is
        # already durable, this only misses a live push.
        logger.warning("could not publish notification for user %s", user_id)


def subscribe(job_id: str) -> Iterator[dict[str, Any]]:
    """Yields live job-progress events until the caller stops consuming."""
    yield from _subscribe_channel(channel_for(job_id))


def subscribe_notifications(user_id: str) -> Iterator[dict[str, Any]]:
    """Yields live notification events for one user until the caller stops consuming."""
    yield from _subscribe_channel(channel_for_user(user_id))


def _subscribe_channel(channel: str) -> Iterator[dict[str, Any]]:
    pubsub = get_redis().pubsub(ignore_subscribe_messages=True)
    pubsub.subscribe(channel)
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
