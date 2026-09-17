"""Redis pub/sub bridge for job progress, user notifications and canvas changes.

Pub/sub only carries the live tail. For job progress the durable record is
`JobEvent` in Postgres, and a reconnecting client backfills from there using
`Last-Event-ID`, so a dropped message is never lost — only delayed until the
next poll. For notifications the durable record is the `Notification` row
itself, polled via `GET /v1/notifications`; the stream here is a live-update
convenience on top of that, not the source of truth. For canvases the durable
record is `CanvasChange`, read back through `graph_service.changes_since`, so
the same rule holds: a dropped frame costs latency, never data.
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
CANVAS_CHANNEL_PREFIX = "canvas-changes:"
SUBSCRIBE_TIMEOUT_SECONDS = 1.0


def channel_for(job_id: str) -> str:
    return f"{CHANNEL_PREFIX}{job_id}"


def channel_for_user(user_id: str) -> str:
    return f"{NOTIFICATION_CHANNEL_PREFIX}{user_id}"


def channel_for_canvas(canvas_id: str) -> str:
    """One channel per canvas, not per viewer.

    A canvas is a shared surface — the owner in two tabs and a co-creator in a
    third all want the same frames — so the fan-out belongs to the canvas, and
    each connection subscribes to it.
    """
    return f"{CANVAS_CHANNEL_PREFIX}{canvas_id}"


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


def publish_canvas_change(canvas_id: str, payload: dict[str, Any]) -> None:
    try:
        get_redis().publish(channel_for_canvas(canvas_id), json.dumps(payload, ensure_ascii=False))
    except redis.RedisError:
        # Best-effort, same as the other two: `CanvasChange` is already
        # committed, so a lost frame only delays convergence until the client's
        # next write or reconnect, both of which carry a catch-up read.
        logger.warning("could not publish change for canvas %s", canvas_id)


def subscribe(job_id: str) -> Iterator[dict[str, Any]]:
    """Yields live job-progress events until the caller stops consuming."""
    yield from _subscribe_channel(channel_for(job_id))


def subscribe_notifications(user_id: str) -> Iterator[dict[str, Any]]:
    """Yields live notification events for one user until the caller stops consuming."""
    yield from _subscribe_channel(channel_for_user(user_id))


def subscribe_canvas(canvas_id: str) -> Iterator[dict[str, Any]]:
    """Yields live canvas changes until the caller stops consuming."""
    yield from _subscribe_channel(channel_for_canvas(canvas_id))


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
