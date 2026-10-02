"""The suite cannot reach the network or a real object store.

Covers `tests/conftest.py`'s two autouse fixtures: `_block_outbound_network`
(`tests/network_guard.py`) and `_memory_storage` (`tests/memory_storage.py`).
Without them, a developer whose `back/.env` points `STORAGE_BACKEND` at
Tencent COS writes every upload/export/provider test into the real bucket.
"""

from __future__ import annotations

import hashlib
import socket

import httpx
import pytest

from app.config import get_settings
from app.domain.errors import NotFound
from app.storage import s3
from tests.memory_storage import MemoryStorageBackend
from tests.network_guard import OutboundNetworkBlocked, is_local

# TEST-NET-3 (RFC 5737): documentation-only, never routable.
PUBLIC_ADDRESS = ("203.0.113.10", 443)


def test_connecting_a_socket_to_a_public_address_is_refused() -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(OutboundNetworkBlocked):
            sock.connect(PUBLIC_ADDRESS)
        with pytest.raises(OutboundNetworkBlocked):
            sock.connect_ex(PUBLIC_ADDRESS)
    finally:
        sock.close()


def test_resolving_a_public_hostname_is_refused() -> None:
    with pytest.raises(OutboundNetworkBlocked):
        socket.getaddrinfo("api.example.com", 443)
    with pytest.raises(OutboundNetworkBlocked):
        socket.create_connection(PUBLIC_ADDRESS, timeout=1)


def test_http_clients_fail_like_an_offline_machine() -> None:
    with pytest.raises(httpx.ConnectError):
        httpx.get("https://api.example.com/v1/models", timeout=1)


def test_loopback_stays_reachable() -> None:
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    try:
        port = server.getsockname()[1]
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            pass
        # Resolving `localhost` is allowed as well; which address family the
        # OS then tries first (IPv6 `::1` on macOS) is not the guard's concern.
        assert socket.getaddrinfo("localhost", port)
    finally:
        server.close()


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("127.0.0.1", True),
        ("::1", True),
        ("[::1]", True),
        ("localhost", True),
        (None, True),
        ("203.0.113.10", False),
        ("10.0.0.5", False),
        ("cos.ap-guangzhou.myqcloud.com", False),
    ],
)
def test_only_loopback_counts_as_local(host: object, expected: bool) -> None:
    assert is_local(host) is expected


def test_cos_is_disabled_and_minio_is_the_configured_backend() -> None:
    settings = get_settings()
    assert settings.storage_backend == "minio"
    assert settings.cos_secret_id == ""
    assert settings.cos_secret_key == ""


def test_object_store_is_the_in_memory_backend(_memory_storage: MemoryStorageBackend) -> None:
    payload = b"probe"
    s3.put_object("guard/probe.txt", payload, content_type="text/plain")
    assert _memory_storage.objects["guard/probe.txt"] == (payload, "text/plain")
    assert s3.head_object("guard/probe.txt") == {
        "size_bytes": len(payload),
        "content_type": "text/plain",
        "etag": hashlib.md5(payload, usedforsecurity=False).hexdigest(),
    }

    s3.move_object("guard/probe.txt", "guard/moved.txt")
    assert s3.head_object("guard/probe.txt") is None
    assert s3.get_object("guard/moved.txt") == payload

    s3.delete_object("guard/moved.txt")
    with pytest.raises(NotFound):
        s3.get_object("guard/moved.txt")
    assert s3.bucket_usage() == {"object_count": 0, "total_bytes": 0, "by_prefix": {}}


def test_each_test_starts_with_an_empty_store(_memory_storage: MemoryStorageBackend) -> None:
    # `test_object_store_is_the_in_memory_backend` wrote objects above; a fresh
    # backend per test means nothing leaks between tests.
    assert _memory_storage.objects == {}


def test_presigned_urls_carry_the_bucket_and_key() -> None:
    url = s3.presign_get("guard/a b.png", expires_in=60, download_name="a.png")
    assert url.startswith(get_settings().s3_public_endpoint_url.rstrip("/") + "/")
    assert f"/{s3.active_bucket_name()}/guard/a%20b.png?X-Amz-Expires=60" in url
    assert "response-content-disposition=" in url
