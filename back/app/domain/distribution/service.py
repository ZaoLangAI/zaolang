"""Connect/callback/list/disconnect + one-click fan-out publish.

This module is the only thing in the codebase that talks to a `PlatformClient`
directly — everything else (the API layer, other domains) goes through the
functions here, never `DouyinClient`/`KuaishouClient` themselves. That keeps
the `{channel: PlatformClient}` registry the single place a TikTok/Xiaohongshu
implementation would be added later.

Fan-out publishing never lets one bad channel fail the whole request: a
channel with no configured app credentials, or no linked account, is recorded
as a skipped manual-style intent (same as today's `MANUAL_DOWNLOAD` path)
rather than raising, and a channel whose real publish call fails marks that
one `PublicationIntent` `FAILED` without touching the others.
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import json
import time
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.domain.distribution import crypto
from app.domain.distribution.client_base import PlatformClient
from app.domain.distribution.douyin_client import DouyinClient
from app.domain.distribution.kuaishou_client import KuaishouClient
from app.domain.errors import (
    DomainError,
    Forbidden,
    NotFound,
    PlatformOAuthFailed,
    PlatformPublishFailed,
    ValidationFailed,
)
from app.domain.shortform import service as shortform_service
from app.models import (
    Asset,
    DramaEpisode,
    EpisodeExternalMetric,
    EpisodeExternalMetricDaily,
    PlatformAccountDailyStat,
    PlatformAccountLink,
    PublicationIntent,
    Series,
    Work,
    WorkVersion,
)
from app.models.base import utcnow
from app.models.enums import DistributionChannel, PlatformAccountLinkStatus, PublicationStatus
from app.storage import s3

# A stale or replayed OAuth callback is rejected past this age.
STATE_TTL_SECONDS = 600

_CLIENTS: dict[str, PlatformClient] = {
    DistributionChannel.DOUYIN.value: DouyinClient(),
    DistributionChannel.KUAISHOU.value: KuaishouClient(),
}


@dataclass(slots=True)
class PublicationResult:
    """One channel's outcome from `publish_fanout`."""

    channel: str
    status: str
    external_post_id: str | None = None
    error: str | None = None
    # Set only for a channel that was skipped rather than attempted, e.g.
    # "manual_download", "not_configured", "not_linked".
    reason: str | None = None


@dataclass(slots=True)
class SeriesMetricsChannelTotal:
    channel: str
    view_count: int
    like_count: int
    comment_count: int
    share_count: int
    like_rate: float
    comment_rate: float
    share_rate: float
    engagement_rate: float


@dataclass(slots=True)
class SeriesMetricsEpisodeRow:
    episode_id: str
    episode_number: int
    episode_title: str
    channel: str
    view_count: int
    like_count: int
    comment_count: int
    share_count: int
    like_rate: float
    comment_rate: float
    share_rate: float
    engagement_rate: float
    finish_rate: float | None
    avg_play_duration_ms: int | None
    fetched_at: dt.datetime


@dataclass(slots=True)
class SeriesMetricsDailyPoint:
    date: dt.date
    channel: str
    view_count: int
    like_count: int
    comment_count: int
    share_count: int


@dataclass(slots=True)
class SeriesFollowerDailyPoint:
    date: dt.date
    channel: str
    follower_count: int


@dataclass(slots=True)
class SeriesMetricsPeriodComparison:
    channel: str
    view_count_change_pct: float | None
    like_count_change_pct: float | None
    comment_count_change_pct: float | None
    share_count_change_pct: float | None


@dataclass(slots=True)
class SeriesDistributionCoverage:
    total_episodes: int
    episodes_with_final_cut: int
    episodes_distributed: int
    channels_covered: list[str]


@dataclass(slots=True)
class _ChannelCounts:
    """Internal accumulator — never returned across the service boundary."""

    view_count: int = 0
    like_count: int = 0
    comment_count: int = 0
    share_count: int = 0


_ZERO_COUNTS = _ChannelCounts()


def _safe_rate(numerator: int, denominator: int) -> float:
    """`numerator / denominator`, rounded to 4dp — `0.0` rather than a
    `ZeroDivisionError` when nothing has been viewed yet."""
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


def config_status() -> dict[str, bool]:
    """`{channel: bool}` — true iff that channel's AppKey/AppSecret are both set."""
    settings = get_settings()
    return {
        DistributionChannel.DOUYIN.value: bool(
            settings.douyin_app_key and settings.douyin_app_secret
        ),
        DistributionChannel.KUAISHOU.value: bool(
            settings.kuaishou_app_id and settings.kuaishou_app_secret
        ),
    }


def connect_start(session: Session, *, user_id: str, channel: str) -> str:
    """Returns the authorize URL a creator is redirected to.

    Session is unused today (no DB write happens before the redirect) but
    kept in the signature for symmetry with the other functions here and in
    case a future revision wants to record the connect attempt.
    """
    _ = session
    client = _client_for(channel)
    state = _sign_state(user_id=user_id, channel=channel)
    return client.authorize_url(state)


def connect_callback(
    session: Session, *, channel: str, code: str, state: str
) -> PlatformAccountLink:
    """Verifies `state`, exchanges `code`, and upserts the `PlatformAccountLink`.

    The state check happens before any other work — an invalid or stale state
    is rejected before the code is ever exchanged.
    """
    user_id = _verify_state(state, expected_channel=channel)
    client = _client_for(channel)
    tokens = client.exchange_code(code)

    expires_at = (
        utcnow() + dt.timedelta(seconds=tokens.expires_in) if tokens.expires_in else None
    )
    access_token_encrypted = crypto.encrypt_token(tokens.access_token)
    refresh_token_encrypted = (
        crypto.encrypt_token(tokens.refresh_token) if tokens.refresh_token else None
    )

    existing = session.scalar(
        select(PlatformAccountLink).where(
            PlatformAccountLink.user_id == user_id,
            PlatformAccountLink.channel == channel,
            PlatformAccountLink.external_account_id == tokens.open_id,
        )
    )
    if existing is not None:
        existing.access_token_encrypted = access_token_encrypted
        existing.refresh_token_encrypted = refresh_token_encrypted
        existing.token_expires_at = expires_at
        existing.status = PlatformAccountLinkStatus.ACTIVE
        existing.revoked_at = None
        existing.last_refreshed_at = utcnow()
        session.flush()
        return existing

    link = PlatformAccountLink(
        user_id=user_id,
        channel=channel,
        external_account_id=tokens.open_id,
        access_token_encrypted=access_token_encrypted,
        refresh_token_encrypted=refresh_token_encrypted,
        token_expires_at=expires_at,
        scopes_json=[],
        status=PlatformAccountLinkStatus.ACTIVE,
    )
    session.add(link)
    session.flush()
    return link


def list_linked_accounts(session: Session, *, user_id: str) -> list[PlatformAccountLink]:
    return list(
        session.scalars(
            select(PlatformAccountLink)
            .where(
                PlatformAccountLink.user_id == user_id,
                PlatformAccountLink.status == PlatformAccountLinkStatus.ACTIVE,
            )
            .order_by(PlatformAccountLink.connected_at.desc())
        )
    )


def list_metrics_for_work(session: Session, *, user_id: str, work_id: str) -> list[EpisodeExternalMetric]:
    """Every channel's latest pulled snapshot for one work, ownership-checked.

    Read-only — the pull itself only ever happens on `pull_episode_metrics`'s
    own beat schedule, never synchronously in a request.
    """
    work = session.get(Work, work_id)
    if work is None:
        raise NotFound("作品不存在。")
    if work.owner_user_id != user_id:
        raise Forbidden("只能查看自己作品的数据。")
    return list(
        session.scalars(
            select(EpisodeExternalMetric)
            .where(EpisodeExternalMetric.work_id == work_id)
            .order_by(EpisodeExternalMetric.channel.asc())
        )
    )


def _authorize_series(session: Session, *, user_id: str, series_id: str) -> Series:
    series = session.get(Series, series_id)
    if series is None:
        raise NotFound("剧集不存在。")
    if series.owner_user_id != user_id:
        raise Forbidden("只能查看自己剧集的数据。")
    return series


def _series_final_cut_episodes(
    session: Session, *, user_id: str, series_id: str
) -> list[DramaEpisode]:
    """Ownership-checked episodes that have something published to measure —
    shared by every `series_metrics_*`/`series_distribution_coverage`
    function below so the auth check and the "only final cuts count" filter
    live in exactly one place.
    """
    _authorize_series(session, user_id=user_id, series_id=series_id)
    return list(
        session.scalars(
            select(DramaEpisode).where(
                DramaEpisode.series_id == series_id,
                DramaEpisode.canonical_work_id.is_not(None),
            )
        )
    )


def series_metrics_summary(
    session: Session, *, user_id: str, series_id: str
) -> tuple[list[SeriesMetricsChannelTotal], list[SeriesMetricsEpisodeRow]]:
    """Aggregates every episode's final-cut metrics into per-channel totals
    (the series page's overview cards) and a per-episode × channel
    breakdown (the detail page's table). Only episodes with a
    `canonical_work_id` set contribute — an episode with no final cut yet
    has nothing published to measure. Read-only, same as
    `list_metrics_for_work` — no synchronous platform call happens here.
    """
    episodes = _series_final_cut_episodes(session, user_id=user_id, series_id=series_id)
    if not episodes:
        return [], []
    work_ids = [episode.canonical_work_id for episode in episodes if episode.canonical_work_id]
    metrics = list(
        session.scalars(
            select(EpisodeExternalMetric).where(EpisodeExternalMetric.work_id.in_(work_ids))
        )
    )
    episode_by_work_id = {episode.canonical_work_id: episode for episode in episodes}
    rows: list[SeriesMetricsEpisodeRow] = []
    totals_counts: dict[str, _ChannelCounts] = {}
    for metric in metrics:
        episode = episode_by_work_id.get(metric.work_id)
        if episode is None:
            continue
        rows.append(
            SeriesMetricsEpisodeRow(
                episode_id=episode.id,
                episode_number=episode.episode_number,
                episode_title=episode.title,
                channel=metric.channel,
                view_count=metric.view_count,
                like_count=metric.like_count,
                comment_count=metric.comment_count,
                share_count=metric.share_count,
                like_rate=_safe_rate(metric.like_count, metric.view_count),
                comment_rate=_safe_rate(metric.comment_count, metric.view_count),
                share_rate=_safe_rate(metric.share_count, metric.view_count),
                engagement_rate=_safe_rate(
                    metric.like_count + metric.comment_count + metric.share_count,
                    metric.view_count,
                ),
                finish_rate=(
                    metric.finish_rate_bp / 10000 if metric.finish_rate_bp is not None else None
                ),
                avg_play_duration_ms=metric.avg_play_duration_ms,
                fetched_at=metric.fetched_at,
            )
        )
        counts = totals_counts.setdefault(metric.channel, _ChannelCounts())
        counts.view_count += metric.view_count
        counts.like_count += metric.like_count
        counts.comment_count += metric.comment_count
        counts.share_count += metric.share_count
    rows.sort(key=lambda row: (row.episode_number, row.channel))
    totals = [
        SeriesMetricsChannelTotal(
            channel=channel,
            view_count=counts.view_count,
            like_count=counts.like_count,
            comment_count=counts.comment_count,
            share_count=counts.share_count,
            like_rate=_safe_rate(counts.like_count, counts.view_count),
            comment_rate=_safe_rate(counts.comment_count, counts.view_count),
            share_rate=_safe_rate(counts.share_count, counts.view_count),
            engagement_rate=_safe_rate(
                counts.like_count + counts.comment_count + counts.share_count, counts.view_count
            ),
        )
        for channel, counts in totals_counts.items()
    ]
    totals.sort(key=lambda item: item.channel)
    return totals, rows


def series_metrics_timeseries(
    session: Session, *, user_id: str, series_id: str, days: int = 30
) -> list[SeriesMetricsDailyPoint]:
    """One point per `(day, channel)` in the trailing `days`-day window —
    each point is the point-in-time sum, across every final-cut episode, of
    that post's cumulative counts as of that day (not a daily delta; see
    `EpisodeExternalMetricDaily`'s docstring). Missing days are zero-filled
    for whichever channels have *any* data in the window, mirroring
    `app.domain.statistics.service`'s zero-fill convention so the frontend
    trend chart never reads a gap as "no data returned".
    """
    episodes = _series_final_cut_episodes(session, user_id=user_id, series_id=series_id)
    work_ids = [episode.canonical_work_id for episode in episodes if episode.canonical_work_id]
    if not work_ids:
        return []
    today = utcnow().date()
    start = today - dt.timedelta(days=days - 1)
    rows = session.execute(
        select(
            EpisodeExternalMetricDaily.metric_date,
            EpisodeExternalMetricDaily.channel,
            func.sum(EpisodeExternalMetricDaily.view_count).label("view_count"),
            func.sum(EpisodeExternalMetricDaily.like_count).label("like_count"),
            func.sum(EpisodeExternalMetricDaily.comment_count).label("comment_count"),
            func.sum(EpisodeExternalMetricDaily.share_count).label("share_count"),
        )
        .where(
            EpisodeExternalMetricDaily.work_id.in_(work_ids),
            EpisodeExternalMetricDaily.metric_date >= start,
        )
        .group_by(EpisodeExternalMetricDaily.metric_date, EpisodeExternalMetricDaily.channel)
    ).all()
    if not rows:
        return []
    channels = sorted({row.channel for row in rows})
    by_key = {(row.metric_date, row.channel): row for row in rows}
    all_days = [start + dt.timedelta(days=offset) for offset in range(days)]
    points: list[SeriesMetricsDailyPoint] = []
    for day in all_days:
        for channel in channels:
            row = by_key.get((day, channel))
            points.append(
                SeriesMetricsDailyPoint(
                    date=day,
                    channel=channel,
                    view_count=int(row.view_count) if row else 0,
                    like_count=int(row.like_count) if row else 0,
                    comment_count=int(row.comment_count) if row else 0,
                    share_count=int(row.share_count) if row else 0,
                )
            )
    return points


def series_followers_timeseries(
    session: Session, *, user_id: str, series_id: str, days: int = 30
) -> list[SeriesFollowerDailyPoint]:
    """Same day-window shape as `series_metrics_timeseries`, but account-
    level: every channel this series' owner has an active link to, not just
    channels a post was published on. No delta computation, same reasoning
    as the view-count trend — see `series_metrics_timeseries`'s docstring.
    """
    _authorize_series(session, user_id=user_id, series_id=series_id)
    links = list(
        session.scalars(
            select(PlatformAccountLink).where(
                PlatformAccountLink.user_id == user_id,
                PlatformAccountLink.status == PlatformAccountLinkStatus.ACTIVE,
            )
        )
    )
    if not links:
        return []
    link_channel = {link.id: link.channel for link in links}
    link_ids = list(link_channel)
    today = utcnow().date()
    start = today - dt.timedelta(days=days - 1)
    rows = list(
        session.scalars(
            select(PlatformAccountDailyStat).where(
                PlatformAccountDailyStat.link_id.in_(link_ids),
                PlatformAccountDailyStat.metric_date >= start,
                PlatformAccountDailyStat.follower_count.is_not(None),
            )
        )
    )
    if not rows:
        return []
    channels = sorted({link_channel[row.link_id] for row in rows if row.link_id in link_channel})
    by_key: dict[tuple[dt.date, str], int] = {}
    for row in rows:
        channel = link_channel.get(row.link_id)
        if channel is None or row.follower_count is None:
            continue
        by_key[(row.metric_date, channel)] = row.follower_count
    all_days = [start + dt.timedelta(days=offset) for offset in range(days)]
    points: list[SeriesFollowerDailyPoint] = []
    last_known: dict[str, int] = {}
    for day in all_days:
        for channel in channels:
            value = by_key.get((day, channel))
            if value is not None:
                last_known[channel] = value
            if channel in last_known:
                points.append(
                    SeriesFollowerDailyPoint(
                        date=day, channel=channel, follower_count=last_known[channel]
                    )
                )
    return points


def _channel_totals_as_of(
    session: Session, *, work_ids: list[str], boundary: dt.date
) -> dict[str, _ChannelCounts]:
    """Per-channel sum of each post's latest cumulative snapshot at or
    before `boundary` — the building block `series_metrics_period_comparison`
    uses to turn three points in time into two periods' worth of growth.
    """
    if not work_ids:
        return {}
    latest = (
        select(
            EpisodeExternalMetricDaily.work_id,
            EpisodeExternalMetricDaily.channel,
            EpisodeExternalMetricDaily.external_post_id,
            func.max(EpisodeExternalMetricDaily.metric_date).label("metric_date"),
        )
        .where(
            EpisodeExternalMetricDaily.work_id.in_(work_ids),
            EpisodeExternalMetricDaily.metric_date <= boundary,
        )
        .group_by(
            EpisodeExternalMetricDaily.work_id,
            EpisodeExternalMetricDaily.channel,
            EpisodeExternalMetricDaily.external_post_id,
        )
        .subquery()
    )
    rows = session.execute(
        select(
            EpisodeExternalMetricDaily.channel,
            func.sum(EpisodeExternalMetricDaily.view_count).label("view_count"),
            func.sum(EpisodeExternalMetricDaily.like_count).label("like_count"),
            func.sum(EpisodeExternalMetricDaily.comment_count).label("comment_count"),
            func.sum(EpisodeExternalMetricDaily.share_count).label("share_count"),
        )
        .join(
            latest,
            (EpisodeExternalMetricDaily.work_id == latest.c.work_id)
            & (EpisodeExternalMetricDaily.channel == latest.c.channel)
            & (EpisodeExternalMetricDaily.external_post_id == latest.c.external_post_id)
            & (EpisodeExternalMetricDaily.metric_date == latest.c.metric_date),
        )
        .group_by(EpisodeExternalMetricDaily.channel)
    ).all()
    return {
        row.channel: _ChannelCounts(
            view_count=int(row.view_count or 0),
            like_count=int(row.like_count or 0),
            comment_count=int(row.comment_count or 0),
            share_count=int(row.share_count or 0),
        )
        for row in rows
    }


def _period_growth_pct(now: int, mid: int, start: int) -> float | None:
    """`None` whenever the prior period had zero-or-negative growth to
    compare against — dividing by a non-positive baseline produces a number
    that looks precise but means nothing, so the API omits it rather than
    let the frontend render a misleading percentage.
    """
    previous_delta = mid - start
    if previous_delta <= 0:
        return None
    current_delta = now - mid
    return round(current_delta / previous_delta - 1, 4)


def series_metrics_period_comparison(
    session: Session, *, user_id: str, series_id: str, days: int = 30
) -> list[SeriesMetricsPeriodComparison]:
    """Growth this `days`-day window vs. the equal-length window before it,
    per channel — see `_period_growth_pct` for why a channel can come back
    with `None`s instead of a percentage.
    """
    episodes = _series_final_cut_episodes(session, user_id=user_id, series_id=series_id)
    work_ids = [episode.canonical_work_id for episode in episodes if episode.canonical_work_id]
    if not work_ids:
        return []
    today = utcnow().date()
    boundary_mid = today - dt.timedelta(days=days)
    boundary_start = today - dt.timedelta(days=2 * days)
    totals_now = _channel_totals_as_of(session, work_ids=work_ids, boundary=today)
    totals_mid = _channel_totals_as_of(session, work_ids=work_ids, boundary=boundary_mid)
    totals_start = _channel_totals_as_of(session, work_ids=work_ids, boundary=boundary_start)
    channels = sorted(set(totals_now) | set(totals_mid) | set(totals_start))
    results: list[SeriesMetricsPeriodComparison] = []
    for channel in channels:
        now = totals_now.get(channel, _ZERO_COUNTS)
        mid = totals_mid.get(channel, _ZERO_COUNTS)
        start = totals_start.get(channel, _ZERO_COUNTS)
        results.append(
            SeriesMetricsPeriodComparison(
                channel=channel,
                view_count_change_pct=_period_growth_pct(
                    now.view_count, mid.view_count, start.view_count
                ),
                like_count_change_pct=_period_growth_pct(
                    now.like_count, mid.like_count, start.like_count
                ),
                comment_count_change_pct=_period_growth_pct(
                    now.comment_count, mid.comment_count, start.comment_count
                ),
                share_count_change_pct=_period_growth_pct(
                    now.share_count, mid.share_count, start.share_count
                ),
            )
        )
    return results


def series_distribution_coverage(
    session: Session, *, user_id: str, series_id: str
) -> SeriesDistributionCoverage:
    """How much of the series has actually shipped: episodes with a final
    cut, episodes with at least one channel actually distributed to, and
    which channels those are. `EXPORTED`/`SUBMITTED` both count as
    "distributed" — `EXPORTED` is `MANUAL_DOWNLOAD`'s only completion state
    today, `SUBMITTED` is the OAuth direct-publish path's (see
    `PublicationStatus`'s docstring for why nothing reaches it yet).
    """
    _authorize_series(session, user_id=user_id, series_id=series_id)
    all_episodes = list(
        session.scalars(select(DramaEpisode).where(DramaEpisode.series_id == series_id))
    )
    total_episodes = len(all_episodes)
    work_ids = [episode.canonical_work_id for episode in all_episodes if episode.canonical_work_id]
    if not work_ids:
        return SeriesDistributionCoverage(
            total_episodes=total_episodes,
            episodes_with_final_cut=0,
            episodes_distributed=0,
            channels_covered=[],
        )
    distributed_statuses = (PublicationStatus.EXPORTED.value, PublicationStatus.SUBMITTED.value)
    intents = list(
        session.scalars(
            select(PublicationIntent).where(
                PublicationIntent.work_id.in_(work_ids),
                PublicationIntent.status.in_(distributed_statuses),
            )
        )
    )
    return SeriesDistributionCoverage(
        total_episodes=total_episodes,
        episodes_with_final_cut=len(work_ids),
        episodes_distributed=len({intent.work_id for intent in intents}),
        channels_covered=sorted({intent.channel for intent in intents}),
    )


def disconnect(session: Session, *, user_id: str, link_id: str) -> PlatformAccountLink:
    """Tombstones the link (`status=revoked`) — never a hard delete."""
    link = session.get(PlatformAccountLink, link_id)
    if link is None:
        raise NotFound("未找到该平台账号连接。")
    if link.user_id != user_id:
        raise Forbidden("不能操作他人的平台账号连接。")
    link.status = PlatformAccountLinkStatus.REVOKED
    link.revoked_at = utcnow()
    session.flush()
    return link


def publish_fanout(
    session: Session,
    *,
    user_id: str,
    work_id: str,
    channels: Sequence[str],
    title: str,
    description: str | None,
    hashtags: Sequence[str],
) -> list[PublicationResult]:
    """One `PublicationIntent` per requested channel, real-pushed where possible.

    Ownership of `work_id` is checked once per channel by
    `shortform_service.create_publication_intent` (via its own `_owned_work`)
    — the same helper the existing single-channel publish route already
    relies on, so a work belonging to another user 404s/403s exactly as it
    does there, before any platform call is attempted.
    """
    results: list[PublicationResult] = []
    for channel in channels:
        bundle = shortform_service.create_publication_intent(
            session,
            user_id=user_id,
            work_id=work_id,
            channel=channel,
            title=title,
            description=description,
            hashtags=hashtags,
        )
        intent = bundle.intent

        if channel == DistributionChannel.MANUAL_DOWNLOAD.value:
            results.append(
                PublicationResult(channel=channel, status=intent.status, reason="manual_download")
            )
            continue

        client = _CLIENTS.get(channel)
        if client is None or not config_status().get(channel, False):
            results.append(
                PublicationResult(channel=channel, status=intent.status, reason="not_configured")
            )
            continue

        link = _active_link(session, user_id=user_id, channel=channel)
        if link is None:
            results.append(
                PublicationResult(channel=channel, status=intent.status, reason="not_linked")
            )
            continue

        try:
            _push_to_platform(
                session,
                client=client,
                link=link,
                intent=intent,
                title=title,
                description=description,
                hashtags=hashtags,
            )
            results.append(
                PublicationResult(
                    channel=channel,
                    status=intent.status,
                    external_post_id=intent.external_post_id,
                )
            )
        except DomainError as exc:
            shortform_service.mark_failed(session, intent)
            results.append(
                PublicationResult(channel=channel, status=intent.status, error=exc.message)
            )

    session.flush()
    return results


def pull_episode_metrics(session: Session) -> int:
    """Refreshes `EpisodeExternalMetric` (latest snapshot) and
    `EpisodeExternalMetricDaily` (today's row — upserted in place, so a
    second run the same day never grows a duplicate) for every submitted
    post still on a real platform channel, then does the same for linked
    accounts' follower counts via `_pull_account_stats`. Called from
    `app.workers.tasks.pull_episode_metrics` on its own beat schedule, never
    synchronously from a request.

    One post's failure (an expired token, a transient network error) is
    logged into nothing and simply skipped — it never stops the sweep from
    reaching the next post, and next run's pull tries it again.
    """
    intents = list(
        session.scalars(
            select(PublicationIntent).where(
                PublicationIntent.status == PublicationStatus.SUBMITTED,
                PublicationIntent.channel.in_(
                    [DistributionChannel.DOUYIN.value, DistributionChannel.KUAISHOU.value]
                ),
                PublicationIntent.external_post_id.is_not(None),
            )
        )
    )
    today = utcnow().date()
    pulled = 0
    for intent in intents:
        client = _CLIENTS.get(intent.channel)
        if client is None:
            continue
        link = _active_link(session, user_id=intent.user_id, channel=intent.channel)
        if link is None:
            continue
        try:
            access_token = crypto.decrypt_token(link.access_token_encrypted)
            snapshot = client.fetch_metrics(
                access_token, link.external_account_id, intent.external_post_id or ""
            )
        except DomainError:
            continue

        existing = session.scalar(
            select(EpisodeExternalMetric).where(
                EpisodeExternalMetric.work_id == intent.work_id,
                EpisodeExternalMetric.channel == intent.channel,
                EpisodeExternalMetric.external_post_id == intent.external_post_id,
            )
        )
        if existing is None:
            existing = EpisodeExternalMetric(
                work_id=intent.work_id,
                channel=intent.channel,
                external_post_id=intent.external_post_id,
            )
            session.add(existing)
        existing.view_count = snapshot.view_count
        existing.like_count = snapshot.like_count
        existing.comment_count = snapshot.comment_count
        existing.share_count = snapshot.share_count
        existing.finish_rate_bp = snapshot.finish_rate_bp
        existing.avg_play_duration_ms = snapshot.avg_play_duration_ms
        existing.fetched_at = utcnow()

        daily = session.scalar(
            select(EpisodeExternalMetricDaily).where(
                EpisodeExternalMetricDaily.work_id == intent.work_id,
                EpisodeExternalMetricDaily.channel == intent.channel,
                EpisodeExternalMetricDaily.external_post_id == intent.external_post_id,
                EpisodeExternalMetricDaily.metric_date == today,
            )
        )
        if daily is None:
            daily = EpisodeExternalMetricDaily(
                work_id=intent.work_id,
                channel=intent.channel,
                external_post_id=intent.external_post_id,
                metric_date=today,
            )
            session.add(daily)
        daily.view_count = snapshot.view_count
        daily.like_count = snapshot.like_count
        daily.comment_count = snapshot.comment_count
        daily.share_count = snapshot.share_count
        daily.finish_rate_bp = snapshot.finish_rate_bp
        daily.avg_play_duration_ms = snapshot.avg_play_duration_ms
        daily.fetched_at = utcnow()
        pulled += 1

    _pull_account_stats(session, today=today)

    session.commit()
    return pulled


def _pull_account_stats(session: Session, *, today: dt.date) -> None:
    """Best-effort follower-count snapshot for every active platform link,
    one upserted row per `(link, today)` — same "in-place per day" shape as
    the episode daily table. A link whose client call fails is skipped
    silently, same policy as the per-post loop above.
    """
    links = list(
        session.scalars(
            select(PlatformAccountLink).where(
                PlatformAccountLink.status == PlatformAccountLinkStatus.ACTIVE,
                PlatformAccountLink.channel.in_(
                    [DistributionChannel.DOUYIN.value, DistributionChannel.KUAISHOU.value]
                ),
            )
        )
    )
    for link in links:
        client = _CLIENTS.get(link.channel)
        if client is None:
            continue
        try:
            access_token = crypto.decrypt_token(link.access_token_encrypted)
            stats = client.fetch_account_stats(access_token, link.external_account_id)
        except DomainError:
            continue
        if stats.follower_count is None:
            continue

        daily = session.scalar(
            select(PlatformAccountDailyStat).where(
                PlatformAccountDailyStat.link_id == link.id,
                PlatformAccountDailyStat.metric_date == today,
            )
        )
        if daily is None:
            daily = PlatformAccountDailyStat(link_id=link.id, metric_date=today)
            session.add(daily)
        daily.follower_count = stats.follower_count
        daily.fetched_at = utcnow()


# --- internals -------------------------------------------------------------


def _push_to_platform(
    session: Session,
    *,
    client: PlatformClient,
    link: PlatformAccountLink,
    intent: PublicationIntent,
    title: str,
    description: str | None,
    hashtags: Sequence[str],
) -> None:
    file_bytes = _asset_bytes_for_work(session, intent.work_id)
    if not file_bytes:
        raise PlatformPublishFailed("作品没有可用的成片文件。")

    # Decrypted only for the lifetime of this call — never persisted, never
    # logged, never put in an exception message.
    access_token = crypto.decrypt_token(link.access_token_encrypted)
    ticket = client.init_upload(access_token)
    video_id = client.upload_video(ticket, file_bytes)
    caption = _compose_caption(title, description, hashtags)
    result = client.create_post(access_token, link.external_account_id, video_id, caption)
    shortform_service.mark_submitted(
        session, intent, external_post_id=result.item_id or result.video_id
    )


def _compose_caption(title: str, description: str | None, hashtags: Sequence[str]) -> str:
    parts = [title]
    if description:
        parts.append(description)
    if hashtags:
        parts.append(" ".join(f"#{tag}" for tag in hashtags))
    return "\n".join(part for part in parts if part)


def _asset_bytes_for_work(session: Session, work_id: str) -> bytes | None:
    work = session.get(Work, work_id)
    if work is None or not work.current_version_id:
        return None
    version = session.get(WorkVersion, work.current_version_id)
    if version is None or not version.primary_output_asset_id:
        return None
    asset = session.get(Asset, version.primary_output_asset_id)
    if asset is None:
        return None
    return s3.get_object(asset.object_key)


def _active_link(session: Session, *, user_id: str, channel: str) -> PlatformAccountLink | None:
    return session.scalar(
        select(PlatformAccountLink).where(
            PlatformAccountLink.user_id == user_id,
            PlatformAccountLink.channel == channel,
            PlatformAccountLink.status == PlatformAccountLinkStatus.ACTIVE,
        )
    )


def _client_for(channel: str) -> PlatformClient:
    client = _CLIENTS.get(channel)
    if client is None:
        raise ValidationFailed(f"不支持的分发渠道: {channel}")
    return client


def _sign_state(*, user_id: str, channel: str) -> str:
    """HMAC-signs `{user_id, channel, ts}` with `settings.jwt_secret`.

    Reuses the JWT secret rather than inventing a new one: it is already an
    env-sourced value with the right entropy for HMAC-SHA256, and rotating it
    already has an established operational story.
    """
    payload = {"user_id": user_id, "channel": channel, "ts": int(time.time())}
    payload_b64 = _b64_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    return f"{payload_b64}.{_hmac(payload_b64)}"


def _verify_state(state: str, *, expected_channel: str) -> str:
    try:
        payload_b64, signature = state.split(".", 1)
    except ValueError as exc:
        raise PlatformOAuthFailed("授权状态无效。") from exc

    if not hmac.compare_digest(signature, _hmac(payload_b64)):
        raise PlatformOAuthFailed("授权状态签名校验失败。")

    try:
        payload = json.loads(_b64_decode(payload_b64).decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise PlatformOAuthFailed("授权状态无效。") from exc

    if not isinstance(payload, dict) or payload.get("channel") != expected_channel:
        raise PlatformOAuthFailed("授权状态渠道不匹配。")

    issued_at = payload.get("ts")
    # A small negative allowance absorbs clock skew between processes; a
    # state minted more than `STATE_TTL_SECONDS` in the past is stale.
    if not isinstance(issued_at, int) or not (-60 <= time.time() - issued_at <= STATE_TTL_SECONDS):
        raise PlatformOAuthFailed("授权状态已过期，请重新发起连接。")

    user_id = payload.get("user_id")
    if not isinstance(user_id, str) or not user_id:
        raise PlatformOAuthFailed("授权状态无效。")
    return user_id


def _hmac(payload_b64: str) -> str:
    settings = get_settings()
    return hmac.new(
        settings.jwt_secret.encode("utf-8"), payload_b64.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def _b64_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64_decode(value: str) -> bytes:
    padded = value + "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii"))
