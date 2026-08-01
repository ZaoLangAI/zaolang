"""Celery configuration.

Five queues, split by latency profile rather than by feature. A four-minute
video render must never sit behind — or in front of — a two-second moderation
check, so they get separate workers that can be scaled independently.
"""

from __future__ import annotations

from celery import Celery
from kombu import Queue

from app.config import get_settings

settings = get_settings()

celery_app = Celery("zaolang", broker=settings.redis_url, backend=settings.redis_url)

QUEUE_NAMES = (
    "moderation_short",
    "image_generation",
    "video_generation_long",
    "quality_check",
    "webhook_reconcile",
)

celery_app.conf.update(
    task_queues=[Queue(name) for name in QUEUE_NAMES],
    task_default_queue="image_generation",
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    # A task that vanishes mid-flight must be retried, and one worker must not
    # hoard a queue while another idles.
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_track_started=True,
    result_expires=60 * 60 * 24,
    broker_connection_retry_on_startup=True,
    task_routes={
        "app.workers.tasks.run_moderation": {"queue": "moderation_short"},
        "app.workers.tasks.run_generation": {"queue": "image_generation"},
        "app.workers.tasks.run_video_generation": {"queue": "video_generation_long"},
        "app.workers.tasks.run_quality_check": {"queue": "quality_check"},
        "app.workers.tasks.reconcile_webhooks": {"queue": "webhook_reconcile"},
        "app.workers.tasks.expire_stale_jobs": {"queue": "webhook_reconcile"},
    },
    beat_schedule={
        "expire-stale-jobs": {
            "task": "app.workers.tasks.expire_stale_jobs",
            "schedule": 300.0,
        },
        "reconcile-credits": {
            "task": "app.workers.tasks.reconcile_credits",
            "schedule": 3600.0,
        },
    },
)

celery_app.autodiscover_tasks(["app.workers"])
