"""Pluggable per-platform client interface.

Mirrors `app.storage.base.StorageBackend`: a small ABC so a concrete platform
implementation (`DouyinClient`, `KuaishouClient`) can be swapped in behind a
`{channel: PlatformClient}` registry (`app.domain.distribution.service`),
leaving room for a TikTok/Xiaohongshu implementation later without touching
the service layer.

Every method's very first statement in a concrete implementation must be a
check that the relevant `Settings` app key/secret is non-empty, raising
`app.domain.errors.PlatformNotConfigured` before any `httpx` call is
attempted — see `douyin_client.py`/`kuaishou_client.py`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TokenBundle:
    access_token: str
    refresh_token: str | None
    expires_in: int
    open_id: str


@dataclass(frozen=True, slots=True)
class UploadTicket:
    upload_token: str
    upload_server_uri: str


@dataclass(frozen=True, slots=True)
class PublishResult:
    item_id: str | None
    video_id: str | None
    error_code: int


@dataclass(frozen=True, slots=True)
class MetricsSnapshot:
    view_count: int
    like_count: int
    comment_count: int
    share_count: int
    # Best-effort extras: neither platform's response shape has been
    # confirmed against live docs for these two (see the disclaimers at the
    # top of `douyin_client.py`/`kuaishou_client.py`), so both stay `None`
    # whenever the raw payload doesn't carry a recognized key.
    finish_rate_bp: int | None = None
    avg_play_duration_ms: int | None = None


@dataclass(frozen=True, slots=True)
class AccountStatsSnapshot:
    follower_count: int | None


class PlatformClient(ABC):
    """One short-video platform's OAuth + upload + publish + metrics surface."""

    @abstractmethod
    def authorize_url(self, state: str) -> str:
        """The URL a creator is redirected to in order to grant this app
        permission to publish on their behalf."""

    @abstractmethod
    def exchange_code(self, code: str) -> TokenBundle:
        """Trades an OAuth `code` for an access/refresh token pair."""

    @abstractmethod
    def refresh_token(self, refresh_token: str) -> TokenBundle:
        """Exchanges a refresh token for a fresh access token."""

    @abstractmethod
    def init_upload(self, access_token: str) -> UploadTicket:
        """Opens an upload session, returning the ticket the next call needs."""

    @abstractmethod
    def upload_video(self, ticket: UploadTicket, file_bytes: bytes) -> str:
        """Uploads the video binary, returning the platform's `video_id`."""

    @abstractmethod
    def create_post(
        self, access_token: str, open_id: str, video_id: str, caption: str
    ) -> PublishResult:
        """Publishes an already-uploaded video, entering that platform's
        review/audit queue."""

    @abstractmethod
    def fetch_metrics(self, access_token: str, open_id: str, item_id: str) -> MetricsSnapshot:
        """Basic play/like/comment/share counts for a published item, plus
        best-effort finish-rate/watch-time if the raw response happens to
        carry them (see `MetricsSnapshot`).

        Called from `app.domain.distribution.service.pull_episode_metrics`
        on its own beat schedule.
        """

    @abstractmethod
    def fetch_account_stats(self, access_token: str, open_id: str) -> AccountStatsSnapshot:
        """Best-effort follower count for the linked account.

        Same caveat as `fetch_metrics`'s extra fields: the endpoint/field
        name is not confirmed against live docs, so a missing/unrecognized
        key yields `follower_count=None` rather than raising.
        """
