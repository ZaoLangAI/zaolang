"""Daily time-series statistics for the back-office analytics module.

Snapshot-style stats (current provider pool, current agent usage, current
reconciliation) already live in `observability.py`, `jobs.py` and
`ledger.py`. These endpoints add the trend dimension those snapshots lack,
one grouped `date_trunc` query per domain — see `app/domain/statistics`.
"""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Query

from app.api.deps import DbSession
from app.api.schemas.admin import (
    AgentDailyPoint,
    AgentTimeseriesView,
    ContentDailyPoint,
    ContentTimeseriesView,
    CreditFlowDailyPoint,
    CreditFlowTimeseriesView,
    JobsDailyPoint,
    JobsTimeseriesView,
    ProviderDailyPoint,
    ProviderTimeseriesView,
    UserGrowthDailyPoint,
    UserGrowthTimeseriesView,
)
from app.api.v1.admin.deps import AdminRead, Viewer
from app.domain.statistics import service as statistics_service
from app.models.base import utcnow

router = APIRouter(prefix="/statistics", tags=["admin:statistics"])


@router.get("/jobs", response_model=JobsTimeseriesView)
def jobs_timeseries(
    session: DbSession,
    user: Viewer,
    _: AdminRead,
    days: int = Query(default=30, ge=1, le=180),
) -> JobsTimeseriesView:
    points = statistics_service.jobs_daily(session, days)
    return JobsTimeseriesView(
        generated_at=utcnow(),
        window_days=days,
        points=[JobsDailyPoint(**asdict(point)) for point in points],
    )


@router.get("/providers", response_model=ProviderTimeseriesView)
def providers_timeseries(
    session: DbSession,
    user: Viewer,
    _: AdminRead,
    days: int = Query(default=30, ge=1, le=180),
) -> ProviderTimeseriesView:
    points = statistics_service.providers_daily(session, days)
    return ProviderTimeseriesView(
        generated_at=utcnow(),
        window_days=days,
        points=[ProviderDailyPoint(**asdict(point)) for point in points],
    )


@router.get("/agents", response_model=AgentTimeseriesView)
def agents_timeseries(
    session: DbSession,
    user: Viewer,
    _: AdminRead,
    days: int = Query(default=30, ge=1, le=180),
) -> AgentTimeseriesView:
    points = statistics_service.agents_daily(session, days)
    return AgentTimeseriesView(
        generated_at=utcnow(),
        window_days=days,
        points=[AgentDailyPoint(**asdict(point)) for point in points],
    )


@router.get("/credits", response_model=CreditFlowTimeseriesView)
def credits_timeseries(
    session: DbSession,
    user: Viewer,
    _: AdminRead,
    days: int = Query(default=30, ge=1, le=180),
) -> CreditFlowTimeseriesView:
    points = statistics_service.credits_daily(session, days)
    return CreditFlowTimeseriesView(
        generated_at=utcnow(),
        window_days=days,
        points=[CreditFlowDailyPoint(**asdict(point)) for point in points],
    )


@router.get("/content", response_model=ContentTimeseriesView)
def content_timeseries(
    session: DbSession,
    user: Viewer,
    _: AdminRead,
    days: int = Query(default=30, ge=1, le=180),
) -> ContentTimeseriesView:
    points = statistics_service.content_daily(session, days)
    return ContentTimeseriesView(
        generated_at=utcnow(),
        window_days=days,
        points=[ContentDailyPoint(**asdict(point)) for point in points],
    )


@router.get("/users", response_model=UserGrowthTimeseriesView)
def users_timeseries(
    session: DbSession,
    user: Viewer,
    _: AdminRead,
    days: int = Query(default=30, ge=1, le=180),
) -> UserGrowthTimeseriesView:
    stats = statistics_service.users_growth(session, days)
    return UserGrowthTimeseriesView(
        generated_at=utcnow(),
        window_days=days,
        points=[UserGrowthDailyPoint(**asdict(point)) for point in stats.points],
        total_users=stats.total_users,
        suspended_users=stats.suspended_users,
    )
