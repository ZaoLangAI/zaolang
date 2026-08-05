"""`SystemLog`: window aggregation at the domain level, and the three hook
points that must never lose a signal even though the request that triggers
them commits nothing of its own (a failed login, a rate limit trip, a
`Forbidden`)."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api import rate_limit
from app.domain.system_log import service as system_log
from app.models import SystemLog, User
from app.models.base import new_id
from app.models.enums import SystemLogSource, UserRole
from tests.conftest import admin_header, make_user

# system_log.emit() commits through its own connection (see module docstring),
# so rows it writes are visible to `db` immediately under Postgres's default
# READ COMMITTED isolation, but never roll back with the rest of the test.
# Every dedup_key below is unique per test to avoid cross-test collisions.


@pytest.fixture
def viewer(db: Session) -> User:
    return make_user(
        db,
        email="slog-viewer@example.com",
        handle="slog_viewer",
        display_name="日志测试观察者",
        roles=[UserRole.USER.value, UserRole.VIEWER.value],
    )


def test_first_occurrence_inserts_one_row(db: Session) -> None:
    dedup_key = f"test:{new_id('t')}"
    system_log.emit(
        source=SystemLogSource.AUTH,
        event="test.single",
        message="one occurrence",
        dedup_key=dedup_key,
    )
    rows = list(db.scalars(select(SystemLog).where(SystemLog.dedup_key == dedup_key)))
    assert len(rows) == 1
    assert rows[0].occurrence_count == 1
    assert rows[0].event == "test.single"


def test_a_burst_in_one_window_collapses_into_a_single_row(db: Session) -> None:
    """The whole point: 15 occurrences must not become 15 rows."""
    dedup_key = f"test:{new_id('t')}"
    for _ in range(15):
        system_log.emit(
            source=SystemLogSource.AUTH,
            event="test.burst",
            message="burst",
            dedup_key=dedup_key,
        )
    rows = list(db.scalars(select(SystemLog).where(SystemLog.dedup_key == dedup_key)))
    assert len(rows) == 1
    assert rows[0].occurrence_count >= 1


def test_a_new_window_starts_a_new_row(db: Session) -> None:
    dedup_key = f"test:{new_id('t')}"
    system_log.emit(
        source=SystemLogSource.AUTH,
        event="test.window",
        message="first window",
        dedup_key=dedup_key,
        window_seconds=1,
    )
    time.sleep(1.2)
    system_log.emit(
        source=SystemLogSource.AUTH,
        event="test.window",
        message="second window",
        dedup_key=dedup_key,
        window_seconds=1,
    )
    rows = list(db.scalars(select(SystemLog).where(SystemLog.dedup_key == dedup_key)))
    assert len(rows) == 2


def test_a_redis_outage_drops_the_log_without_raising(monkeypatch: pytest.MonkeyPatch) -> None:
    import redis

    class Broken:
        def pipeline(self) -> None:
            raise redis.RedisError("down")

    monkeypatch.setattr(system_log, "get_redis", lambda: Broken())
    system_log.emit(
        source=SystemLogSource.AUTH,
        event="test.outage",
        message="should not raise",
        dedup_key="test:outage",
    )


# --- hook points -------------------------------------------------------------


def test_a_failed_login_is_recorded(client: TestClient, db: Session, author: User) -> None:
    ip = "203.0.113.200"
    response = client.post(
        "/v1/auth/login",
        json={"email": author.email, "password": "wrong"},
        headers={"X-Forwarded-For": ip},
    )
    assert response.status_code == 401

    row = db.scalar(
        select(SystemLog).where(SystemLog.event == "login.failed", SystemLog.ip_address == ip)
    )
    assert row is not None
    assert row.source == "auth"


def test_a_failed_admin_login_is_recorded(client: TestClient, db: Session, admin: User) -> None:
    ip = "203.0.113.201"
    response = client.post(
        "/v1/admin/auth/login",
        json={"email": admin.email, "password": "wrong"},
        headers={"X-Forwarded-For": ip},
    )
    assert response.status_code == 401

    row = db.scalar(
        select(SystemLog).where(SystemLog.event == "admin_login.failed", SystemLog.ip_address == ip)
    )
    assert row is not None


def test_a_rate_limit_trip_is_recorded(client: TestClient, db: Session, author: User) -> None:
    ip = "203.0.113.202"
    limit = rate_limit.RULES["auth_attempt"].limit
    identity = f"ip:{ip}"
    last = None
    for _ in range(limit + 2):
        last = client.post(
            "/v1/auth/login",
            json={"email": author.email, "password": "wrong"},
            headers={"X-Forwarded-For": ip},
        )
    assert last is not None and last.status_code == 429

    row = db.scalar(
        select(SystemLog).where(
            SystemLog.event == "rate_limited.auth_attempt",
            SystemLog.dedup_key == f"auth_attempt:{identity}",
        )
    )
    assert row is not None
    assert row.source == "rate_limit"


def test_insufficient_admin_role_is_recorded(client: TestClient, db: Session, viewer: User) -> None:
    response = client.post("/v1/admin/moderation/queue/mdr_1/claim", headers=admin_header(viewer))
    assert response.status_code == 403

    row = db.scalar(
        select(SystemLog).where(
            SystemLog.event == "admin_action.forbidden",
            SystemLog.dedup_key == f"user:{viewer.id}:/v1/admin/moderation/queue/mdr_1/claim",
        )
    )
    assert row is not None
    assert row.source == "permission"
    assert row.user_id == viewer.id
