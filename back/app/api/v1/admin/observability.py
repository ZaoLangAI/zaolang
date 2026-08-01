"""System health, provider statistics and agent-run inspection."""

from __future__ import annotations

import datetime as dt
import time

from fastapi import APIRouter, Query
from sqlalchemy import Integer, func, select, text

from app.api.deps import DbSession
from app.api.schemas.admin import (
    AgentRunView,
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
from app.models import AgentRun, GenerationJob, ProviderStat
from app.models.base import utcnow
from app.platform_config import service as config_service
from app.platform_config.schemas import ProviderConfig
from app.workers.celery_app import QUEUE_NAMES

router = APIRouter(tags=["admin:observability"])

# Below this many attempts the measured rate is noise, so the router uses a
# conservative prior instead. The console shows the same threshold.
MIN_ATTEMPTS_FOR_CONFIDENCE = 20


@router.get("/health", response_model=SystemHealthResponse)
def system_health(session: DbSession, user: Viewer, _: AdminRead) -> SystemHealthResponse:
    settings = get_settings()
    services = [
        _probe("postgres", lambda: _isolated_query(session, "SELECT 1")),
        _probe("redis", _ping_redis),
        _probe("minio", _ping_storage),
        _probe("celery", _ping_celery),
    ]
    return SystemHealthResponse(
        services=services,
        queues=_queue_depths(),
        alembic_revision=_alembic_revision(session),
        llm_mode=settings.effective_llm_mode,
        llm_reachable=_llm_reachable(),
        app_version=settings.app_version,
        generated_at=utcnow(),
    )


@router.get("/providers/stats", response_model=Page[ProviderStatView])
def provider_stats(session: DbSession, user: Viewer, _: AdminRead) -> Page[ProviderStatView]:
    """What the router actually sees when it scores candidates."""
    config = config_service.get_typed(session, "providers", ProviderConfig)
    disabled = {name for name, setting in config.providers.items() if not setting.enabled}

    items = []
    for stat in session.scalars(select(ProviderStat).order_by(ProviderStat.provider)):
        success_rate = (stat.successes / stat.attempts) if stat.attempts else 0.0
        avg_latency = int(stat.total_latency_ms / stat.attempts) if stat.attempts else 0
        effective_cost = int(stat.total_cost_minor / stat.successes) if stat.successes else 0
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
                effective_cost=effective_cost,
                enabled=stat.provider not in disabled,
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


@router.get("/agent-runs", response_model=Page[AgentRunView])
def list_agent_runs(
    session: DbSession,
    user: Viewer,
    _: AdminRead,
    agent_name: str | None = None,
    job_id: str | None = None,
    degraded_only: bool = False,
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> Page[AgentRunView]:
    stmt = select(AgentRun).order_by(AgentRun.created_at.desc(), AgentRun.id.desc())
    if agent_name:
        stmt = stmt.where(AgentRun.agent_name == agent_name)
    if job_id:
        stmt = stmt.where(AgentRun.job_id == job_id)
    if degraded_only:
        stmt = stmt.where(AgentRun.degraded.is_(True))
    if cursor:
        stmt = stmt.where(AgentRun.id < cursor)

    rows = list(session.scalars(stmt.limit(limit + 1)))
    has_more = len(rows) > limit
    page = rows[:limit]
    return Page(
        items=[_agent_run_view(run) for run in page],
        next_cursor=page[-1].id if has_more and page else None,
        has_more=has_more,
    )


@router.get("/workflow", response_model=dict)
def workflow_shape(user: Viewer, _: AdminRead) -> dict:
    """The declared pipeline, used to render a timeline even for a job that
    failed before emitting its later steps."""
    from app.workflows import describe_workflow

    return describe_workflow()


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


def _agent_run_view(run: AgentRun) -> AgentRunView:
    return AgentRunView(
        id=run.id,
        agent_name=run.agent_name,
        model=run.model or "",
        mode=run.mode,
        degraded=run.degraded,
        prompt_tokens=run.prompt_tokens,
        completion_tokens=run.completion_tokens,
        latency_ms=run.latency_ms,
        status=run.status,
        error_message=run.degrade_reason,
        job_id=run.job_id,
        created_at=run.created_at,
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


def _llm_reachable() -> bool | None:
    """None means "not applicable" — stub mode never touches the gateway."""
    from app.llm import client as llm_client

    if get_settings().effective_llm_mode == "stub":
        return None
    return bool(llm_client.probe().get("reachable"))
