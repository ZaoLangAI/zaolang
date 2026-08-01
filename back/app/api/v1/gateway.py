"""Public read-only view of the smart gateway.

The create page tells the user what the gateway is doing on their behalf, and
the plan requires a degraded gateway to be visible in the product rather than
only in the ops console. Everything here is aggregate: no provider names, no
model bindings, no keys.
"""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter
from sqlalchemy import func, select

from app.agents.router import PROVIDER_CATALOG
from app.api.deps import DbSession
from app.api.schemas.common import ApiModel
from app.config import get_settings
from app.models import AgentRun, ProviderStat
from app.models.enums import ProviderKind
from app.platform_config import service as config_service
from app.platform_config.schemas import ProviderConfig

router = APIRouter(tags=["gateway"])

DEGRADED_WINDOW = dt.timedelta(hours=24)


class GatewayStatusResponse(ApiModel):
    """Aggregate health of the generation gateway."""

    available_routes: int
    """Provider routes currently enabled and usable."""

    savings_percent: int
    """How much cheaper the routed mix has been than always taking the
    commercial route, over all recorded attempts."""

    status: str
    """`healthy`, `degraded` or `down`."""

    mode: str
    degraded_runs_24h: int


@router.get("/gateway/status", response_model=GatewayStatusResponse)
def gateway_status(session: DbSession) -> GatewayStatusResponse:
    provider_config = config_service.get_typed(session, "providers", ProviderConfig)

    enabled = [
        capability
        for name, capability in PROVIDER_CATALOG.items()
        if (setting := provider_config.providers.get(name)) is not None and setting.enabled
    ]

    since = dt.datetime.now(dt.UTC) - DEGRADED_WINDOW
    degraded_runs = (
        session.scalar(
            select(func.count())
            .select_from(AgentRun)
            .where(AgentRun.degraded.is_(True), AgentRun.created_at >= since)
        )
        or 0
    )

    if not enabled:
        status = "down"
    elif degraded_runs > 0:
        status = "degraded"
    else:
        status = "healthy"

    return GatewayStatusResponse(
        available_routes=len(enabled),
        savings_percent=_savings_percent(session),
        status=status,
        mode=get_settings().effective_llm_mode,
        degraded_runs_24h=int(degraded_runs),
    )


def _savings_percent(session: DbSession) -> int:
    """Actual spend against the counterfactual of always paying.

    Zero when nothing has run yet — an invented number here would be the kind
    of marketing claim the product must not make.
    """
    baseline_unit = max(
        (
            c.unit_cost_minor
            for c in PROVIDER_CATALOG.values()
            if c.kind == ProviderKind.COMMERCIAL_API
        ),
        default=0,
    )
    if baseline_unit == 0:
        return 0

    row = session.execute(
        select(
            func.coalesce(func.sum(ProviderStat.attempts), 0),
            func.coalesce(func.sum(ProviderStat.total_cost_minor), 0),
        )
    ).one()
    attempts, spent = int(row[0]), int(row[1])
    if attempts == 0:
        return 0

    baseline = attempts * baseline_unit
    return max(0, min(99, round((baseline - spent) / baseline * 100)))
