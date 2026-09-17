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
    CostBreakdownView,
    CostDailyPoint,
    CostTimeseriesView,
    CreditFlowDailyPoint,
    CreditFlowTimeseriesView,
    JobsDailyPoint,
    JobsTimeseriesView,
    ModelCostView,
    ProviderCostSeriesView,
    ProviderDailyPoint,
    ProviderTimeseriesView,
    UserGrowthDailyPoint,
    UserGrowthTimeseriesView,
)
from app.api.v1.admin.deps import AdminRead, Viewer
from app.domain.statistics import service as statistics_service
from app.models.base import utcnow
from app.platform_config import service as config_service
from app.platform_config.schemas import LlmProviderConfig

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


@router.get("/costs", response_model=CostTimeseriesView)
def costs_timeseries(
    session: DbSession,
    user: Viewer,
    _: AdminRead,
    days: int = Query(default=30, ge=1, le=180),
) -> CostTimeseriesView:
    """Daily spend on model vendors, split into text and media.

    Every point was priced when the call happened, so re-reading an old
    window never changes what it says. Calls served by an endpoint with no
    configured price contribute nothing — unknown, not free.
    """
    points = statistics_service.cost_daily(session, days)
    return CostTimeseriesView(
        generated_at=utcnow(),
        window_days=days,
        points=[_cost_point(point) for point in points],
        total_micro_usd=sum(point.total_micro_usd for point in points),
    )


@router.get("/costs/breakdown", response_model=CostBreakdownView)
def costs_breakdown(
    session: DbSession,
    user: Viewer,
    _: AdminRead,
    days: int = Query(default=30, ge=1, le=180),
) -> CostBreakdownView:
    """The same window, cut by vendor endpoint and by model.

    Endpoint names come from the live config, so an endpoint deleted since
    the spend happened still reports its id with a blank name rather than
    dropping the money it cost.
    """
    config = config_service.get_typed(session, "llm_providers", LlmProviderConfig)
    names = {endpoint_id: e.name for endpoint_id, e in config.endpoints.items()}
    return CostBreakdownView(
        generated_at=utcnow(),
        window_days=days,
        providers=[
            ProviderCostSeriesView(
                endpoint_id=series.endpoint_id,
                endpoint_name=names.get(series.endpoint_id, ""),
                total_micro_usd=series.total_micro_usd,
                points=[_cost_point(point) for point in series.points],
            )
            for series in statistics_service.cost_by_provider_daily(session, days)
        ],
        models=[
            ModelCostView(
                model=stat.model,
                endpoint_id=stat.endpoint_id,
                endpoint_name=names.get(stat.endpoint_id, ""),
                kind=stat.kind,
                calls=stat.calls,
                total_micro_usd=stat.total_micro_usd,
            )
            for stat in statistics_service.cost_by_model(session, days)
        ],
    )


def _cost_point(point: statistics_service.CostDailyStat) -> CostDailyPoint:
    return CostDailyPoint(
        date=point.date,
        llm_micro_usd=point.llm_micro_usd,
        media_micro_usd=point.media_micro_usd,
        total_micro_usd=point.total_micro_usd,
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
