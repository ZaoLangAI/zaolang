"""Selects the active `StorageBackend` from `settings.storage_backend`."""

from __future__ import annotations

from functools import lru_cache

from app.config import get_settings
from app.storage.backends.minio import MinioBackend
from app.storage.backends.minio import reset_client_cache as _reset_minio_clients
from app.storage.backends.tencent_cos import TencentCosBackend
from app.storage.backends.tencent_cos import reset_client_cache as _reset_cos_clients
from app.storage.base import StorageBackend


@lru_cache
def get_backend() -> StorageBackend:
    settings = get_settings()
    if settings.storage_backend == "tencent_cos":
        return TencentCosBackend()
    return MinioBackend()


def reset_backend_cache() -> None:
    get_backend.cache_clear()
    _reset_minio_clients()
    _reset_cos_clients()
