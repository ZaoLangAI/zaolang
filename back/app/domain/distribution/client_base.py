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
        """Basic play/like/comment/share counts for a published item.

        Nothing calls this yet — Phase D wires up the polling that does. The
        signature exists now so the interface is complete.
        """
