"""In-process `StorageBackend` every test uses unless it opts out.

`back/.env` is read by the test suite too, and a developer who switched
`STORAGE_BACKEND` to Tencent COS would otherwise have every upload, export and
provider test write into the real bucket with real credentials. The autouse
`_memory_storage` fixture in `tests/conftest.py` swaps this backend in behind
`app.storage.s3` (the only caller of any backend), so storage behaves the same
on every machine and never leaves the process. Mark a test `real_storage` to
talk to the configured MinIO instead.
"""

from __future__ import annotations

import hashlib
import mimetypes
from typing import Any
from urllib.parse import quote

from app.config import get_settings
from app.domain.errors import NotFound
from app.storage.base import StorageBackend


class MemoryStorageBackend(StorageBackend):
    def __init__(self) -> None:
        # object key -> (payload, content type)
        self.objects: dict[str, tuple[bytes, str]] = {}
        self.rules: list[dict[str, Any]] = []

    def active_bucket_name(self) -> str:
        return get_settings().s3_bucket

    def ensure_bucket(self) -> None:
        return None

    def head_bucket(self) -> None:
        return None

    def _signed_url(self, object_key: str, expires_in: int) -> str:
        # Same shape as the MinIO backend's path-style presigned URL — including
        # a signature parameter, since some tests assert a URL is signed — so
        # code that only inspects the host/key/query sees what it saw before.
        endpoint = get_settings().s3_public_endpoint_url.rstrip("/")
        signature = hashlib.sha256(f"{object_key}:{expires_in}".encode()).hexdigest()
        return (
            f"{endpoint}/{self.active_bucket_name()}/{quote(object_key)}"
            f"?X-Amz-Expires={expires_in}&X-Amz-Signature={signature}"
        )

    def presign_put(self, object_key: str, *, content_type: str, expires_in: int) -> str:
        return self._signed_url(object_key, expires_in)

    def presign_get(
        self, object_key: str, *, expires_in: int, download_name: str | None = None
    ) -> str:
        url = self._signed_url(object_key, expires_in)
        if download_name:
            disposition = quote(f'attachment; filename="{download_name}"')
            url += f"&response-content-disposition={disposition}"
        return url

    def put_object(
        self, object_key: str, payload: bytes, *, content_type: str | None = None
    ) -> None:
        resolved = content_type or mimetypes.guess_type(object_key)[0] or "application/octet-stream"
        self.objects[object_key] = (bytes(payload), resolved)

    def get_object(self, object_key: str) -> bytes:
        entry = self.objects.get(object_key)
        if entry is None:
            raise NotFound("对象不存在。")
        return entry[0]

    def head_object(self, object_key: str) -> dict[str, Any] | None:
        entry = self.objects.get(object_key)
        if entry is None:
            return None
        payload, content_type = entry
        return {
            "size_bytes": len(payload),
            "content_type": content_type,
            "etag": hashlib.md5(payload, usedforsecurity=False).hexdigest(),
        }

    def delete_object(self, object_key: str) -> None:
        self.objects.pop(object_key, None)

    def move_object(self, source_key: str, target_key: str) -> None:
        entry = self.objects.pop(source_key, None)
        if entry is None:
            raise NotFound("对象不存在。")
        self.objects[target_key] = entry

    def bucket_usage(self) -> dict[str, Any]:
        by_prefix: dict[str, int] = {}
        for key, (payload, _) in self.objects.items():
            prefix = key.split("/", 1)[0] or "(root)"
            by_prefix[prefix] = by_prefix.get(prefix, 0) + len(payload)
        return {
            "object_count": len(self.objects),
            "total_bytes": sum(len(payload) for payload, _ in self.objects.values()),
            "by_prefix": by_prefix,
        }

    def lifecycle_rules(self) -> list[dict[str, Any]]:
        return [dict(rule) for rule in self.rules]

    def put_lifecycle_rules(self, rules: list[dict[str, Any]]) -> None:
        self.rules = [dict(rule) for rule in rules]
