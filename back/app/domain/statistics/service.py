"""Daily aggregate statistics for the back-office analytics module.

Every `*_daily` function returns one row per UTC calendar day in
`[today - days + 1, today]`, including days with zero activity. A chart that
silently skipped an empty day would read a lull as missing data, so the gap
is always filled with zeros rather than omitted.

All aggregation happens in SQL (`date_trunc` + `group_by`), not by pulling
whole tables into Python — the same guidance `zaolang-admin-ops` gives for
any new statistics endpoint.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from sqlalchemy import Integer, case, func, select
from sqlalchemy.orm import Session

from app.models import (
    AgentRun,
    CreditLedgerEntry,
    GenerationJob,
    LineageEdge,
    ProviderAttempt,
    User,
    Work,
)
from app.models.base import utcnow
from app.models.enums import JobStatus, LedgerEntryType, ProviderAttemptStatus, UserStatus

FAILED_JOB_STATUSES = (
    JobStatus.FAILED.value,
    JobStatus.CANCELLED.value,
    JobStatus.EXPIRED.value,
)


def _window(days: int) -> tuple[dt.date, list[dt.date]]:
    """UTC calendar days `[start, today]`, oldest first."""
    today = utcnow().date()
    start = today - dt.timedelta(days=days - 1)
    return start, [start + dt.timedelta(days=offset) for offset in range(days)]


def _day_bucket(column: object) -> object:
    """Truncate a timestamptz column to its UTC calendar day.

    The explicit `'UTC'` argument matters: plain `date_trunc('day', col)`
    truncates in the session's timezone, which is not guaranteed to be UTC.
    """
    return func.date_trunc("day", column, "UTC")


@dataclass(slots=True)
class JobsDailyStat:
    date: dt.date
    total: int = 0
    succeeded: int = 0
    failed: int = 0
    avg_completion_ms: float | None = None


def jobs_daily(session: Session, days: int) -> list[JobsDailyStat]:
    start, all_days = _window(days)
    completion_ms = (
        func.extract("epoch", GenerationJob.finished_at - GenerationJob.created_at) * 1000
    )
    rows = session.execute(
        select(
            _day_bucket(GenerationJob.created_at).label("day"),
            func.count().label("total"),
            func.sum(
                case((GenerationJob.status == JobStatus.SUCCEEDED.value, 1), else_=0)
            ).label("succeeded"),
            func.sum(case((GenerationJob.status.in_(FAILED_JOB_STATUSES), 1), else_=0)).label(
                "failed"
            ),
            func.avg(
                case(
                    (GenerationJob.status == JobStatus.SUCCEEDED.value, completion_ms),
                    else_=None,
                )
            ).label("avg_completion_ms"),
        )
        .where(GenerationJob.created_at >= start)
        .group_by("day")
    ).all()

    by_day = {row.day.date(): row for row in rows}
    result = []
    for day in all_days:
        row = by_day.get(day)
        result.append(
            JobsDailyStat(
                date=day,
                total=int(row.total) if row else 0,
                succeeded=int(row.succeeded or 0) if row else 0,
                failed=int(row.failed or 0) if row else 0,
                avg_completion_ms=(
                    round(float(row.avg_completion_ms), 1)
                    if row and row.avg_completion_ms is not None
                    else None
                ),
            )
        )
    return result


@dataclass(slots=True)
class ProviderDailyStat:
    date: dt.date
    attempts: int = 0
    successes: int = 0
    avg_latency_ms: float | None = None
    total_cost_minor: int = 0


def providers_daily(session: Session, days: int) -> list[ProviderDailyStat]:
    """Across every provider — per-provider comparison stays on `/providers/stats`."""
    start, all_days = _window(days)
    rows = session.execute(
        select(
            _day_bucket(ProviderAttempt.created_at).label("day"),
            func.count().label("attempts"),
            func.sum(
                case(
                    (ProviderAttempt.status == ProviderAttemptStatus.SUCCEEDED.value, 1), else_=0
                )
            ).label("successes"),
            func.avg(
                case(
                    (
                        ProviderAttempt.status == ProviderAttemptStatus.SUCCEEDED.value,
                        ProviderAttempt.latency_ms,
                    ),
                    else_=None,
                )
            ).label("avg_latency_ms"),
            func.sum(ProviderAttempt.cost_minor).label("total_cost_minor"),
        )
        .where(ProviderAttempt.created_at >= start)
        .group_by("day")
    ).all()

    by_day = {row.day.date(): row for row in rows}
    result = []
    for day in all_days:
        row = by_day.get(day)
        result.append(
            ProviderDailyStat(
                date=day,
                attempts=int(row.attempts) if row else 0,
                successes=int(row.successes or 0) if row else 0,
                avg_latency_ms=(
                    round(float(row.avg_latency_ms), 1)
                    if row and row.avg_latency_ms is not None
                    else None
                ),
                total_cost_minor=int(row.total_cost_minor or 0) if row else 0,
            )
        )
    return result


@dataclass(slots=True)
class AgentDailyStat:
    date: dt.date
    runs: int = 0
    degraded_runs: int = 0
    total_tokens: int = 0
    avg_latency_ms: float | None = None


def agents_daily(session: Session, days: int) -> list[AgentDailyStat]:
    start, all_days = _window(days)
    rows = session.execute(
        select(
            _day_bucket(AgentRun.created_at).label("day"),
            func.count().label("runs"),
            func.sum(func.cast(AgentRun.degraded, Integer)).label("degraded_runs"),
            func.sum(AgentRun.prompt_tokens + AgentRun.completion_tokens).label("total_tokens"),
            func.avg(AgentRun.latency_ms).label("avg_latency_ms"),
        )
        .where(AgentRun.created_at >= start)
        .group_by("day")
    ).all()

    by_day = {row.day.date(): row for row in rows}
    result = []
    for day in all_days:
        row = by_day.get(day)
        result.append(
            AgentDailyStat(
                date=day,
                runs=int(row.runs) if row else 0,
                degraded_runs=int(row.degraded_runs or 0) if row else 0,
                total_tokens=int(row.total_tokens or 0) if row else 0,
                avg_latency_ms=(
                    round(float(row.avg_latency_ms), 1)
                    if row and row.avg_latency_ms is not None
                    else None
                ),
            )
        )
    return result


@dataclass(slots=True)
class CreditFlowDailyStat:
    date: dt.date
    granted: int = 0
    purchased: int = 0
    captured: int = 0
    refunded: int = 0
    royalty_out: int = 0
    royalty_in: int = 0
    access_out: int = 0
    access_in: int = 0
    adjustment: int = 0
    # Sum of every entry's signed amount that day, reserve/release included —
    # a sanity total, not a KPI (those two net out over the reservation's life).
    net: int = 0


# Maps `LedgerEntryType` values not covered here (RESERVE / RELEASE) still
# count toward `net`, they just have no dedicated chart series — a temporary
# hold is not "flow" in the way a grant or a capture is.
_CREDIT_TYPE_FIELDS: dict[str, str] = {
    LedgerEntryType.GRANT.value: "granted",
    LedgerEntryType.PURCHASE.value: "purchased",
    LedgerEntryType.CAPTURE.value: "captured",
    LedgerEntryType.REFUND.value: "refunded",
    LedgerEntryType.ROYALTY_OUT.value: "royalty_out",
    LedgerEntryType.ROYALTY_IN.value: "royalty_in",
    LedgerEntryType.ACCESS_OUT.value: "access_out",
    LedgerEntryType.ACCESS_IN.value: "access_in",
    LedgerEntryType.ADJUSTMENT.value: "adjustment",
}


def credits_daily(session: Session, days: int) -> list[CreditFlowDailyStat]:
    start, all_days = _window(days)
    rows = session.execute(
        select(
            _day_bucket(CreditLedgerEntry.created_at).label("day"),
            CreditLedgerEntry.type,
            func.sum(CreditLedgerEntry.amount).label("amount"),
        )
        .where(CreditLedgerEntry.created_at >= start)
        .group_by("day", CreditLedgerEntry.type)
    ).all()

    by_day: dict[dt.date, dict[str, int]] = {}
    for row in rows:
        day = row.day.date()
        by_day.setdefault(day, {})[row.type] = int(row.amount or 0)

    result = []
    for day in all_days:
        amounts = by_day.get(day, {})
        stat = CreditFlowDailyStat(date=day)
        for entry_type, attr in _CREDIT_TYPE_FIELDS.items():
            setattr(stat, attr, amounts.get(entry_type, 0))
        stat.net = sum(amounts.values())
        result.append(stat)
    return result


@dataclass(slots=True)
class ContentDailyStat:
    date: dt.date
    published_works: int = 0
    remix_edges: int = 0


def content_daily(session: Session, days: int) -> list[ContentDailyStat]:
    start, all_days = _window(days)
    published_rows = session.execute(
        select(_day_bucket(Work.published_at).label("day"), func.count().label("count"))
        .where(Work.published_at.is_not(None), Work.published_at >= start)
        .group_by("day")
    ).all()
    remix_rows = session.execute(
        select(_day_bucket(LineageEdge.created_at).label("day"), func.count().label("count"))
        .where(LineageEdge.created_at >= start)
        .group_by("day")
    ).all()

    published_by_day = {row.day.date(): int(row.count) for row in published_rows}
    remix_by_day = {row.day.date(): int(row.count) for row in remix_rows}
    return [
        ContentDailyStat(
            date=day,
            published_works=published_by_day.get(day, 0),
            remix_edges=remix_by_day.get(day, 0),
        )
        for day in all_days
    ]


@dataclass(slots=True)
class UserGrowthDailyStat:
    date: dt.date
    new_users: int = 0


@dataclass(slots=True)
class UserGrowthStats:
    points: list[UserGrowthDailyStat] = field(default_factory=list)
    total_users: int = 0
    suspended_users: int = 0


def users_growth(session: Session, days: int) -> UserGrowthStats:
    """Registrations are a real daily series; suspensions are not — `User`
    has no `suspended_at`, so a suspension trend would be fabricated. The
    suspended count is reported as a current snapshot instead."""
    start, all_days = _window(days)
    rows = session.execute(
        select(_day_bucket(User.created_at).label("day"), func.count().label("count"))
        .where(User.created_at >= start)
        .group_by("day")
    ).all()
    by_day = {row.day.date(): int(row.count) for row in rows}
    points = [UserGrowthDailyStat(date=day, new_users=by_day.get(day, 0)) for day in all_days]

    total_users = int(session.scalar(select(func.count()).select_from(User)) or 0)
    suspended_users = int(
        session.scalar(
            select(func.count())
            .select_from(User)
            .where(User.status == UserStatus.SUSPENDED.value)
        )
        or 0
    )
    return UserGrowthStats(
        points=points, total_users=total_users, suspended_users=suspended_users
    )
