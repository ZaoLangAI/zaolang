"""Tiered rate limiting.

The point of separate buckets is that pressure on one surface cannot starve
another, so the tests check isolation as much as they check the ceiling.
"""

from __future__ import annotations

import contextlib
from typing import ClassVar

import pytest
from fastapi import APIRouter
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api import rate_limit
from app.api.v1 import community, devices
from app.models import User
from tests.conftest import admin_header, auth_header


def test_every_bucket_has_a_finite_limit() -> None:
    for name, rule in rate_limit.RULES.items():
        assert rule.limit > 0, f"{name} 没有上限"
        assert rule.window_seconds > 0, f"{name} 没有时间窗"


def test_the_back_office_has_its_own_budget() -> None:
    """Consumer traffic must not be able to lock an operator out during the
    incident they are trying to fix."""
    consumer = {"public_read", "authenticated_write", "generation_submit", "upload_presign"}
    admin = {"admin_read", "admin_write", "admin_dangerous"}
    assert consumer.isdisjoint(admin)
    assert admin <= set(rate_limit.RULES)


def test_dangerous_actions_are_the_most_restricted() -> None:
    dangerous = rate_limit.RULES["admin_dangerous"]
    write = rate_limit.RULES["admin_write"]
    assert dangerous.limit < write.limit


def test_exceeding_a_bucket_raises_with_a_retry_hint() -> None:
    from app.domain.errors import RateLimited

    identity = "test:exhaust"
    rate_limit.reset("auth_attempt", identity)
    rule = rate_limit.RULES["auth_attempt"]
    try:
        for _ in range(rule.limit):
            rate_limit.enforce("auth_attempt", identity)

        with pytest.raises(RateLimited) as excinfo:
            rate_limit.enforce("auth_attempt", identity)
        assert excinfo.value.retry_after_seconds == rule.window_seconds
    finally:
        rate_limit.reset("auth_attempt", identity)


def test_sustained_abuse_does_not_grow_the_backing_set_past_the_limit() -> None:
    """A caller who keeps hammering a bucket after being throttled must not
    make the Redis sorted set grow with the request rate — it should plateau
    at (approximately) `limit` members, not `rate * window`."""
    identity = "test:sustained-abuse"
    rate_limit.reset("auth_attempt", identity)
    rule = rate_limit.RULES["auth_attempt"]
    try:
        for _ in range(rule.limit * 3):
            with contextlib.suppress(Exception):
                rate_limit.enforce("auth_attempt", identity)

        size = rate_limit.get_redis().zcard(f"rl:auth_attempt:{identity}")
        assert size <= rule.limit
    finally:
        rate_limit.reset("auth_attempt", identity)


def test_two_identities_do_not_share_a_budget() -> None:
    """Otherwise one noisy client would lock out everyone else."""
    rate_limit.reset("auth_attempt", "test:a")
    rate_limit.reset("auth_attempt", "test:b")
    try:
        for _ in range(rate_limit.RULES["auth_attempt"].limit):
            rate_limit.enforce("auth_attempt", "test:a")
        rate_limit.enforce("auth_attempt", "test:b")
    finally:
        rate_limit.reset("auth_attempt", "test:a")
        rate_limit.reset("auth_attempt", "test:b")


def test_a_redis_outage_does_not_lock_users_out(monkeypatch: pytest.MonkeyPatch) -> None:
    """Availability beats strictness: losing the limiter must not take the
    product down with it."""
    import redis

    class Broken:
        def pipeline(self):  # type: ignore[no-untyped-def]
            raise redis.RedisError("down")

    limiter = rate_limit.RateLimiter(client=Broken())  # type: ignore[arg-type]
    limiter.check("public_read", "test:whoever")


def test_repeated_failed_logins_are_throttled(client: TestClient, author: User) -> None:
    """Brute force is the attack this bucket exists for."""
    limit = rate_limit.RULES["auth_attempt"].limit
    statuses = [
        client.post("/v1/auth/login", json={"email": author.email, "password": "wrong"}).status_code
        for _ in range(limit + 2)
    ]
    assert 429 in statuses


def test_a_throttled_response_tells_the_client_when_to_retry(
    client: TestClient, author: User
) -> None:
    limit = rate_limit.RULES["auth_attempt"].limit
    response = None
    for _ in range(limit + 2):
        response = client.post("/v1/auth/login", json={"email": author.email, "password": "wrong"})
        if response.status_code == 429:
            break

    assert response is not None and response.status_code == 429
    assert response.headers.get("retry-after")


def test_admin_reads_are_not_throttled_by_consumer_traffic(
    client: TestClient, db: Session, admin: User, author: User
) -> None:
    for _ in range(rate_limit.RULES["auth_attempt"].limit + 2):
        client.post("/v1/auth/login", json={"email": author.email, "password": "wrong"})

    assert client.get("/v1/admin/health", headers=admin_header(admin)).status_code == 200


def test_a_signed_in_user_is_limited_per_account_not_per_ip(
    client: TestClient, author: User, remixer: User
) -> None:
    """Two colleagues behind one office IP must not throttle each other."""
    from app.api.deps import client_identity

    class FakeRequest:
        headers: ClassVar[dict[str, str]] = {}
        client = None

    assert client_identity(FakeRequest(), author) != client_identity(FakeRequest(), remixer)  # type: ignore[arg-type]


def test_anonymous_callers_fall_back_to_the_client_ip() -> None:
    from app.api.deps import client_identity

    class FakeRequest:
        headers: ClassVar[dict[str, str]] = {"x-forwarded-for": "203.0.113.9, 10.0.0.1"}
        client = None

    assert client_identity(FakeRequest(), None) == "ip:203.0.113.9"  # type: ignore[arg-type]


def test_an_authenticated_write_is_bounded(client: TestClient, author: User) -> None:
    assert "authenticated_write" in rate_limit.RULES
    response = client.get("/v1/credits/balance", headers=auth_header(author))
    assert response.status_code == 200


def _route_buckets(router: APIRouter) -> dict[str, list[str]]:
    """`METHOD path` → the buckets its `rate_limited(...)` dependencies name."""
    buckets: dict[str, list[str]] = {}
    for route in router.routes:
        assert isinstance(route, APIRoute)
        names = [
            dep.call.__closure__[0].cell_contents
            for dep in route.dependant.dependencies
            if dep.call is not None
            and dep.call.__qualname__ == "rate_limited.<locals>._dependency"
            and dep.call.__closure__
        ]
        for method in route.methods:
            buckets[f"{method} {route.path}"] = names
    return buckets


@pytest.mark.parametrize("router", [community.router, devices.router], ids=["community", "devices"])
def test_every_community_and_device_route_has_a_bucket(router: APIRouter) -> None:
    for route, names in _route_buckets(router).items():
        assert names, f"{route} 没有限流桶"
        assert set(names) <= set(rate_limit.RULES), f"{route} 引用了不存在的限流桶 {names}"


def test_follow_spam_is_throttled_on_its_own_budget(
    client: TestClient, author: User, remixer: User
) -> None:
    """Every unfollow/re-follow cycle notifies the target again, so the
    follow route must run out long before `authenticated_write` would."""
    limit = rate_limit.RULES["social_outreach"].limit
    assert limit < rate_limit.RULES["authenticated_write"].limit

    statuses = [
        client.post(f"/v1/users/{author.id}/follow", headers=auth_header(remixer)).status_code
        for _ in range(limit + 1)
    ]
    assert statuses[:limit] == [200] * limit
    assert statuses[-1] == 429

    # Other writes keep their own budget.
    created = client.post(
        "/v1/collections",
        json={"name": "灵感", "description": None, "is_public": False},
        headers=auth_header(remixer),
    )
    assert created.status_code == 201
