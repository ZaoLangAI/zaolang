"""Object storage backend interface.

Mirrors `app.providers.base.GenerationProvider`: a small ABC so a concrete
backend (MinIO today, Tencent COS as well now) can be swapped by config alone.
`app/storage/s3.py` is the only caller of these implementations — it is a
thin facade that dispatches to whichever backend `get_backend()` selects, so
every other module in the codebase keeps calling `app.storage.s3.<fn>` and
stays unaware a backend switch ever happened.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class StorageBackend(ABC):
    @abstractmethod
    def ensure_bucket(self) -> None:
        """Creates the bucket if missing and applies the configured CORS rules."""

    @abstractmethod
    def head_bucket(self) -> None:
        """Liveness probe for the object store. Raises if unreachable."""

    @abstractmethod
    def presign_put(self, object_key: str, *, content_type: str, expires_in: int) -> str:
        """A short-lived URL the browser can PUT to directly.

        The caller must send back the exact same `content_type` as a
        `Content-Type` header — it is bound into the signature.
        """

    @abstractmethod
    def presign_get(
        self, object_key: str, *, expires_in: int, download_name: str | None = None
    ) -> str:
        """A short-lived URL the browser can GET directly."""

    @abstractmethod
    def put_object(
        self, object_key: str, payload: bytes, *, content_type: str | None = None
    ) -> None:
        pass

    @abstractmethod
    def get_object(self, object_key: str) -> bytes:
        """Raises `app.domain.errors.NotFound` if the object does not exist."""

    @abstractmethod
    def head_object(self, object_key: str) -> dict[str, Any] | None:
        """Returns `{"size_bytes", "content_type", "etag"}`, or `None` on a miss."""

    @abstractmethod
    def delete_object(self, object_key: str) -> None:
        pass

    @abstractmethod
    def move_object(self, source_key: str, target_key: str) -> None:
        """Promotes a staged upload to its permanent location (copy + delete)."""

    @abstractmethod
    def bucket_usage(self) -> dict[str, Any]:
        """Returns `{"object_count", "total_bytes", "by_prefix"}`."""

    @abstractmethod
    def lifecycle_rules(self) -> list[dict[str, Any]]:
        """Returns rules shaped like AWS S3's `Rules` list
        (`{"ID", "Status", "Filter": {"Prefix"}, "Expiration": {"Days"}}`),
        regardless of which backend is active."""

    @abstractmethod
    def put_lifecycle_rules(self, rules: list[dict[str, Any]]) -> None:
        """Accepts rules in the same AWS S3-shaped form `lifecycle_rules` returns."""

    @abstractmethod
    def active_bucket_name(self) -> str:
        """The bucket this backend is currently configured to use."""
