"""`storage_backend` selects a `StorageBackend` implementation, not a live call."""

from __future__ import annotations

import pytest

from app.config import Settings
from app.storage import factory
from app.storage.backends.minio import MinioBackend
from app.storage.backends.tencent_cos import TencentCosBackend


@pytest.fixture(autouse=True)
def _reset_backend_cache():
    factory.get_backend.cache_clear()
    yield
    factory.get_backend.cache_clear()


def test_defaults_to_minio(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(factory, "get_settings", lambda: Settings())
    assert isinstance(factory.get_backend(), MinioBackend)


def test_selects_tencent_cos(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(
        storage_backend="tencent_cos",
        cos_secret_id="dummy-id",
        cos_secret_key="dummy-key",
        cos_bucket="zaolang-media-1250000000",
    )
    monkeypatch.setattr(factory, "get_settings", lambda: settings)
    assert isinstance(factory.get_backend(), TencentCosBackend)
