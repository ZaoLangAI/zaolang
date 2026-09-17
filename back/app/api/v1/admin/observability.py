"""System health, provider statistics and agent-run usage."""

from __future__ import annotations

import datetime as dt
import time

from fastapi import APIRouter, Query
from sqlalchemy import Integer, func, select, text

from app.agents.router import build_catalog
from app.api.deps import DbSession
from app.api.schemas.admin import (
    AgentUsageSummary,
    ProviderStatView,
    QueueDepth,
    RoutingReplayResponse,
    ServiceHealth,
    SystemHealthResponse,
)
from app.api.schemas.common import Page
from app.api.v1.admin.deps import AdminRead, Viewer
from app.config import get_settings
from app.domain.errors import NotFound
from app.domain.jobs import async_tasks
from app.models import AgentRun, AsyncProviderTask, GenerationJob, ProviderStat
from app.models.base import utcnow
from app.workers.celery_app import QUEUE_NAMES

router = APIRouter(tags=["admin:observability"])

# Below this many attempts the measured rate is noise, so the router uses a
# conservative prior instead. The console shows the same threshold.
MIN_ATTEMPTS_FOR_CONFIDENCE = 20

# A task this many poll intervals overdue and still unclaimed is not "about
# to be picked up" — it means nobody is ticking. Multiplied rather than a
# fixed number of seconds so it scales if `POLL_INTERVAL_SECONDS` ever changes.
_STALE_POLL_MULTIPLIER = 4


@router.get("/health", response_model=SystemHealthResponse)
def system_health(session: DbSession, user: Viewer, _: AdminRead) -> SystemHealthResponse:
    settings = get_settings()
    services = [
        _probe("postgres", lambda: _isolated_query(session, "SELECT 1")),
        _probe("redis", _ping_redis),
        _probe("minio", _ping_storage),
        _probe("celery", _ping_celery),
        _probe("async_provider_polling", lambda: _ping_async_polling(session)),
    ]
    return SystemHealthResponse(
        services=services,
        queues=_queue_depths(),
        alembic_revision=_alembic_revision(session),
        llm_reachable=_llm_reachable(session),
        app_version=settings.app_version,
        generated_at=utcnow(),
    )


@router.get("/providers/stats", response_model=Page[ProviderStatView])
def provider_stats(session: DbSession, user: Viewer, _: AdminRead) -> Page[ProviderStatView]:
    """What the router actually sees when it scores candidates."""
    enabled = set(build_catalog(session))

    items = []
    for stat in session.scalars(select(ProviderStat).order_by(ProviderStat.provider)):
        success_rate = (stat.successes / stat.attempts) if stat.attempts else 0.0
        avg_latency = int(stat.total_latency_ms / stat.attempts) if stat.attempts else 0
        effective_cost = int(stat.total_cost_micro_usd / stat.successes) if stat.successes else 0
        items.append(
            ProviderStatView(
                provider=stat.provider,
                operation=stat.operation,
                quality_tier=stat.quality_tier,
                attempts=stat.attempts,
                successes=stat.successes,
                success_rate=round(success_rate, 4),
                p50_latency_ms=avg_latency,
                # Without a histogram the tail is approximated; the console
                # labels it as an estimate rather than a measured percentile.
                p95_latency_ms=int(avg_latency * 1.8),
                effective_cost_micro_usd=effective_cost,
                enabled=stat.provider in enabled,
            )
        )
    return Page(items=items)


@router.get("/jobs/{job_id}/routing", response_model=RoutingReplayResponse)
def routing_replay(
    job_id: str, session: DbSession, user: Viewer, _: AdminRead
) -> RoutingReplayResponse:
    """Replays the decision candidate by candidate, including rejects."""
    job = session.get(GenerationJob, job_id)
    if job is None:
        raise NotFound("任务不存在。")
    return RoutingReplayResponse(
        job_id=job.id,
        chosen_provider=job.selected_route_summary_json.get("provider"),
        candidates=list(job.routing_trace_json or []),
    )


@router.get("/workflow", response_model=dict)
def workflow_shape(
    session: DbSession,
    user: Viewer,
    _: AdminRead,
    operation: str = Query(...),
    template_id: str | None = Query(default=None),
) -> dict:
    """The declared pipeline for one operation, used to render a timeline
    even for a job that failed before emitting its later steps.

    Pass a job's own `workflow_template_id` as `template_id` to describe
    exactly what that job ran rather than the operation's current template.
    """
    from app.workflows import describe_workflow

    return describe_workflow(session, operation, template_id=template_id)


@router.get("/agent-runs/usage", response_model=Page[AgentUsageSummary])
def agent_usage(
    session: DbSession, user: Viewer, _: AdminRead, hours: int = Query(default=24, ge=1, le=720)
) -> Page[AgentUsageSummary]:
    since = utcnow() - dt.timedelta(hours=hours)
    rows = session.execute(
        select(
            AgentRun.agent_name,
            func.count().label("runs"),
            func.sum(func.cast(AgentRun.degraded, Integer)).label("degraded_runs"),
            func.sum(AgentRun.prompt_tokens + AgentRun.completion_tokens).label("tokens"),
            func.avg(AgentRun.latency_ms).label("avg_latency"),
        )
        .where(AgentRun.created_at >= since)
        .group_by(AgentRun.agent_name)
    ).all()

    return Page(
        items=[
            AgentUsageSummary(
                agent_name=name,
                runs=int(runs or 0),
                degraded_runs=int(degraded or 0),
                total_tokens=int(tokens or 0),
                avg_latency_ms=int(avg_latency or 0),
            )
            for name, runs, degraded, tokens, avg_latency in rows
        ]
    )


def _probe(name: str, check) -> ServiceHealth:  # type: ignore[no-untyped-def]
    started = time.perf_counter()
    try:
        check()
        return ServiceHealth(
            name=name, healthy=True, latency_ms=round((time.perf_counter() - started) * 1000, 2)
        )
    except Exception as exc:
        # The message is for an operator, so the exception type is useful, but
        # the string is truncated in case a driver embeds a DSN.
        return ServiceHealth(name=name, healthy=False, detail=f"{type(exc).__name__}: {exc}"[:200])


def _ping_redis() -> None:
    from app.api.rate_limit import get_redis

    get_redis().ping()


def _ping_storage() -> None:
    from app.storage import s3

    s3.head_bucket()


def _ping_celery() -> None:
    from app.workers.celery_app import celery_app

    with celery_app.connection_for_read() as connection:
        connection.ensure_connection(max_retries=1)


def _ping_async_polling(session) -> None:  # type: ignore[no-untyped-def]
    """Tests the actual symptom of a dead Beat/poller, not a connectivity proxy.

    `_ping_celery` only proves the broker is reachable, and `_queue_depths()`
    reads Redis list lengths — both look perfectly healthy while Beat is
    down, because a Beat that never ticks never enqueues anything either.
    An `AsyncProviderTask` overdue by several poll intervals and still
    unclaimed means the opposite of "queue empty": there is real work
    (a suspended video/image job) with nobody coming back for it.
    """
    stale_cutoff = utcnow() - dt.timedelta(
        seconds=async_tasks.POLL_INTERVAL_SECONDS * _STALE_POLL_MULTIPLIER
    )
    stale = session.scalar(
        select(func.count())
        .select_from(AsyncProviderTask)
        .where(
            AsyncProviderTask.next_poll_at < stale_cutoff,
            AsyncProviderTask.claimed_at.is_(None),
        )
    )
    if stale:
        raise RuntimeError(
            f"{stale} 个异步供应商任务已逾期超过 "
            f"{async_tasks.POLL_INTERVAL_SECONDS * _STALE_POLL_MULTIPLIER} 秒仍未被认领，"
            "Beat 或 provider_task_polling 的 worker 可能已停跑"
        )


def _queue_depths() -> list[QueueDepth]:
    try:
        from app.api.rate_limit import get_redis

        client = get_redis()
        return [QueueDepth(queue=name, depth=int(client.llen(name) or 0)) for name in QUEUE_NAMES]
    except Exception:
        return [QueueDepth(queue=name, depth=-1) for name in QUEUE_NAMES]


def _isolated_query(session, sql: str):  # type: ignore[no-untyped-def]
    """Runs a probe query without risking the caller's transaction.

    A failed statement aborts the whole Postgres transaction, so a health check
    that hits a missing table would leave the session unusable for every
    subsequent query in the same request. The savepoint confines the damage to
    the probe itself.
    """
    with session.begin_nested():
        return session.execute(text(sql)).scalar()


def _alembic_revision(session) -> str | None:  # type: ignore[no-untyped-def]
    try:
        return _isolated_query(session, "SELECT version_num FROM alembic_version")
    except Exception:
        # A database that has never been migrated is a real state to report,
        # not a reason to fail the health page.
        return None


def _llm_reachable(session) -> bool:  # type: ignore[no-untyped-def]
    from app.llm import client as llm_client

    return bool(llm_client.probe(session).get("reachable"))
