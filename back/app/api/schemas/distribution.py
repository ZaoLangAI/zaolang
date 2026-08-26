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
    fetched_at: dt.datetime


# Kept for callers that want the raw dict shape without importing the
# dataclass from the domain layer.
JsonDict = dict[str, Any]
