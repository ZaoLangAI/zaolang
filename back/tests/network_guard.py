"""Refuses every outbound connection a test did not mean to make.

The suite must stay deterministic, secret-free and free of charge: a test that
reaches a real LLM gateway, media provider or object store can spend money or
write to production storage. `install` swaps `socket.socket.connect`/
`connect_ex` and `socket.getaddrinfo` for versions that only let loopback
through, so Postgres, Redis and in-process test servers keep working while
anything else fails the way it would on an offline machine (an `OSError`,
which httpx surfaces as `ConnectError`). Tests marked `live` opt out — see the
autouse `_block_outbound_network` fixture in `tests/conftest.py`.
"""

from __future__ import annotations

import ipaddress
import socket
from typing import Any

import pytest

_LOCAL_HOSTNAMES = frozenset({"", "localhost", "localhost.localdomain", "ip6-localhost"})


class OutboundNetworkBlocked(OSError):
    """A test tried to reach a non-loopback address."""


def is_local(host: object) -> bool:
    if host is None:
        # `getaddrinfo(None, port)` resolves the wildcard/loopback address.
        return True
    if isinstance(host, bytes):
        host = host.decode("ascii", "ignore")
    if not isinstance(host, str):
        return False
    name = host.strip("[]").split("%", 1)[0].lower()
    if name in _LOCAL_HOSTNAMES:
        return True
    try:
        return ipaddress.ip_address(name).is_loopback
    except ValueError:
        return False


def _blocked(target: object) -> OutboundNetworkBlocked:
    return OutboundNetworkBlocked(
        f"outbound network is blocked in tests: {target!r} "
        "(mark the test `live` if it really has to go online)"
    )


def install(monkeypatch: pytest.MonkeyPatch) -> None:
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_getaddrinfo = socket.getaddrinfo
    unix_family = getattr(socket, "AF_UNIX", None)

    def check(sock: socket.socket, address: Any) -> None:
        if unix_family is not None and sock.family == unix_family:
            return
        host = address[0] if isinstance(address, tuple) and address else address
        if not is_local(host):
            raise _blocked(address)

    def connect(self: socket.socket, address: Any) -> None:
        check(self, address)
        real_connect(self, address)

    def connect_ex(self: socket.socket, address: Any) -> int:
        check(self, address)
        return real_connect_ex(self, address)

    def getaddrinfo(host: Any, *args: Any, **kwargs: Any) -> Any:
        if not is_local(host):
            raise _blocked(host)
        return real_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)
    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
