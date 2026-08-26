"""Celery configuration.

Queues are split by latency profile rather than by feature. A four-minute
video render must never sit behind — or in front of — a quick quality check,
so they get separate workers that can be scaled independently.
"""

from __future__ import annotations

from celery import Celery
from celery.signals import worker_process_init
from kombu import Queue

from app.config import get_settings
from app.domain.jobs import async_tasks

settings = get_settings()

celery_app = Celery("zaolang", broker=settings.redis_url, backend=settings.redis_url)


@worker_process_init.connect
def _reset_db_engine_after_fork(**_kwargs: object) -> None:
    """Drop any engine/pool the parent process may have opened before fork.

    Prefork children that inherit live DB connections can hang on the next
    checkout after an error; rebuilding the cache makes each child own a
    fresh pool.
    """
    from app.db import reset_engine_cache

    reset_engine_cache()


QUEUE_NAMES = (
    "image_generation",
    "video_generation_long",
    "audio_generation",
    "quality_check",
    "webhook_reconcile",
    # Short, frequent ticks that check on renders already running upstream.
    # Its own queue because the tick must stay punctual: behind a video
    # render it would fire minutes late and the heartbeats it exists to
    # produce would stop.
    "provider_task_polling",
    "media_analysis",
    # Real-platform OAuth token refresh and metrics pulls — its own queue so
    # a slow/failing external platform call never competes with, or gets
    # delayed by, the generation-job lifecycle queues above.
    "platform_distribution",
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
        "app.workers.tasks.run_generation": {"queue": "image_generation"},
        "app.workers.tasks.run_video_generation": {"queue": "video_generation_long"},
        "app.workers.tasks.run_audio_generation": {"queue": "audio_generation"},
        "app.workers.tasks.run_quality_check": {"queue": "quality_check"},
        "app.workers.tasks.reconcile_webhooks": {"queue": "webhook_reconcile"},
        "app.workers.tasks.expire_stale_jobs": {"queue": "webhook_reconcile"},
        "app.workers.tasks.expire_stale_input_requests": {"queue": "webhook_reconcile"},
        "app.workers.tasks.poll_async_provider_tasks": {"queue": "provider_task_polling"},
        "app.workers.tasks.run_media_analysis": {"queue": "media_analysis"},
        "app.workers.tasks.run_editor_transcription": {"queue": "media_analysis"},
        "app.workers.tasks.expire_editor_leases": {"queue": "webhook_reconcile"},
        "app.workers.tasks.expire_orphan_editor_uploads": {"queue": "webhook_reconcile"},
        "app.workers.tasks.pull_episode_metrics": {"queue": "platform_distribution"},
        "app.workers.tasks.purge_expired_exports": {"queue": "webhook_reconcile"},
    },
    beat_schedule={
        "expire-stale-jobs": {
            "task": "app.workers.tasks.expire_stale_jobs",
            "schedule": 300.0,
        },
        "expire-stale-input-requests": {
            "task": "app.workers.tasks.expire_stale_input_requests",
            # An author's own deadline (`input_requests.INPUT_TIMEOUT_SECONDS`)
            # is hours away, unlike a provider render's; there is no benefit
            # to checking for it as often as the 5-minute job sweep.
            "schedule": 900.0,
        },
        "poll-async-provider-tasks": {
            "task": "app.workers.tasks.poll_async_provider_tasks",
            "schedule": float(async_tasks.POLL_INTERVAL_SECONDS),
            # Long enough that a tick downloading a finished render does not
            # drop every subsequent beat fire. `claim_due` still makes two
            # overlapping ticks safe.
            "options": {"expires": int(async_tasks.CLAIM_LEASE.total_seconds())},
        },
        "reconcile-credits": {
            "task": "app.workers.tasks.reconcile_credits",
            "schedule": 3600.0,
        },
        "expire-editor-leases": {
            "task": "app.workers.tasks.expire_editor_leases",
            "schedule": 60.0,
        },
        "expire-orphan-editor-uploads": {
            "task": "app.workers.tasks.expire_orphan_editor_uploads",
            "schedule": 300.0,
        },
        # Basic counts only (see distribution service docstring) — hourly is
        # plenty, no need for the tighter cadence the job-lifecycle sweeps use.
        "pull-episode-metrics": {
            "task": "app.workers.tasks.pull_episode_metrics",
            "schedule": 3600.0,
        },
        # Retention is 30 days (`compliance.purge_expired_exports`'s default);
        # once a day is plenty to keep expired export bundles from lingering.
        "purge-expired-exports": {
            "task": "app.workers.tasks.purge_expired_exports",
            "schedule": 86400.0,
        },
    },
)

celery_app.autodiscover_tasks(["app.workers"])
