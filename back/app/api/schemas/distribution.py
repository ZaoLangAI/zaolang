"""Platform account connect/callback/list/disconnect + fan-out publish payloads."""

from __future__ import annotations

import datetime as dt
from typing import Any

from pydantic import Field

from app.api.schemas.common import ApiModel
from app.models.enums import DistributionChannel, PublicationStatus


class ConfigStatusResponse(ApiModel):
    """True iff that channel's AppKey/AppSecret are both set in `Settings`."""

    douyin: bool
    kuaishou: bool


class AuthorizeUrlResponse(ApiModel):
    authorize_url: str


class PlatformAccountLinkResponse(ApiModel):
    id: str
    channel: DistributionChannel
    external_account_id: str
    external_account_label: str | None = None
    status: str
    connected_at: dt.datetime
    token_expires_at: dt.datetime | None = None


class PublicationFanoutRequest(ApiModel):
    channels: list[DistributionChannel] = Field(min_length=1, max_length=8)
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    hashtags: list[str] = Field(default_factory=list, max_length=30)


class PublicationFanoutItem(ApiModel):
    channel: DistributionChannel
    status: PublicationStatus
    external_post_id: str | None = None
    error: str | None = None
    # Set only when the channel was skipped rather than actually attempted —
    # "manual_download", "not_configured", or "not_linked".
    reason: str | None = None


class PublicationFanoutResponse(ApiModel):
    work_id: str
    results: list[PublicationFanoutItem]


class EpisodeExternalMetricResponse(ApiModel):
    channel: DistributionChannel
    external_post_id: str
    view_count: int
    like_count: int
    comment_count: int
    share_count: int
    finish_rate: float | None = None
    avg_play_duration_ms: int | None = None
    fetched_at: dt.datetime


class SeriesMetricsChannelTotal(ApiModel):
    """Per-channel totals across every episode's final cut in a series —
    the compact card row on the series episode-list page."""

    channel: DistributionChannel
    view_count: int
    like_count: int
    comment_count: int
    share_count: int
    like_rate: float
    comment_rate: float
    share_rate: float
    engagement_rate: float


class SeriesMetricsEpisodeRow(ApiModel):
    """One episode × channel breakdown row — the detail page's table."""

    episode_id: str
    episode_number: int
    episode_title: str
    channel: DistributionChannel
    view_count: int
    like_count: int
    comment_count: int
    share_count: int
    like_rate: float
    comment_rate: float
    share_rate: float
    engagement_rate: float
    finish_rate: float | None = None
    avg_play_duration_ms: int | None = None
    fetched_at: dt.datetime


class SeriesMetricsDailyPoint(ApiModel):
    """One `(day, channel)` point on the "播放量趋势" trend chart — a
    point-in-time cumulative sum, not a daily delta (see
    `app.domain.distribution.service.series_metrics_timeseries`)."""

    date: dt.date
    channel: DistributionChannel
    view_count: int
    like_count: int
    comment_count: int
    share_count: int


class SeriesFollowerDailyPoint(ApiModel):
    date: dt.date
    channel: DistributionChannel
    follower_count: int


class SeriesMetricsPeriodComparison(ApiModel):
    """Growth over the selected window vs. the equal-length window before
    it. A `None` field means the prior window had no positive growth to
    compare against — see `_period_growth_pct`'s docstring."""

    channel: DistributionChannel
    view_count_change_pct: float | None = None
    like_count_change_pct: float | None = None
    comment_count_change_pct: float | None = None
    share_count_change_pct: float | None = None


class SeriesDistributionCoverage(ApiModel):
    total_episodes: int
    episodes_with_final_cut: int
    episodes_distributed: int
    channels_covered: list[DistributionChannel]


class SeriesMetricsSummaryResponse(ApiModel):
    totals: list[SeriesMetricsChannelTotal]
    episodes: list[SeriesMetricsEpisodeRow]
    daily: list[SeriesMetricsDailyPoint]
    followers: list[SeriesFollowerDailyPoint]
    period_comparison: list[SeriesMetricsPeriodComparison]
    coverage: SeriesDistributionCoverage


# Kept for callers that want the raw dict shape without importing the
# dataclass from the domain layer.
JsonDict = dict[str, Any]
