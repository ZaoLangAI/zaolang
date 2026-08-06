"""Unified log centre API."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.audit import service as audit
from app.domain.system_log import service as system_log
from app.models import SystemLog, User
from app.models.base import new_id
from app.models.enums import SystemLogLevel, SystemLogSource
from tests.conftest import admin_header


def test_unified_logs_include_audit_and_system_rows(
    client: TestClient, db: Session, admin: User
) -> None:
    dedup_key = f"test:{new_id('t')}"
    system_log.emit(
        source=SystemLogSource.AUTH,
        event="test.unified",
        message="system row",
        dedup_key=dedup_key,
    )
    audit.record(
        db,
        actor=admin,
        action="config.update",
        target_type="platform_config",
        target_id="pricing",
        after={"version": 2},
    )
    db.commit()

    body = client.get("/v1/admin/logs", headers=admin_header(admin)).json()
    sources = {item["source"] for item in body["items"]}
    assert "audit" in sources
    assert "auth" in sources


def test_unified_logs_can_filter_by_source(client: TestClient, db: Session, admin: User) -> None:
    dedup_key = f"test:{new_id('t')}"
    system_log.emit(
        source=SystemLogSource.PERMISSION,
        event="test.filter",
        message="permission row",
        dedup_key=dedup_key,
    )
    audit.record(
        db,
        actor=admin,
        action="announcement.create",
        target_type="announcement",
        target_id="ann_1",
    )
    db.commit()

    body = client.get(
        "/v1/admin/logs",
        params={"source": "permission"},
        headers=admin_header(admin),
    ).json()
    assert body["items"]
    assert {item["source"] for item in body["items"]} == {"permission"}


def test_audit_logs_support_created_range(client: TestClient, admin: User) -> None:
    response = client.get(
        "/v1/admin/audit-logs",
        params={"created_after": "2020-01-01T00:00:00", "created_before": "2030-01-01T00:00:00"},
        headers=admin_header(admin),
    )
    assert response.status_code == 200


def test_unified_logs_pages_with_a_cursor(client: TestClient, db: Session, admin: User) -> None:
    for index in range(3):
        audit.record(
            db,
            actor=admin,
            action="config.update",
            target_type="platform_config",
            target_id=f"key_{index}",
            after={"version": index},
        )
    db.commit()

    first = client.get(
        "/v1/admin/logs", params={"source": "audit", "limit": 2}, headers=admin_header(admin)
    ).json()
    assert first["has_more"] is True

    second = client.get(
        "/v1/admin/logs",
        params={"source": "audit", "limit": 2, "cursor": first["next_cursor"]},
        headers=admin_header(admin),
    ).json()
    first_ids = {item["id"] for item in first["items"]}
    second_ids = {item["id"] for item in second["items"]}
    assert first_ids.isdisjoint(second_ids)


def test_system_log_rows_surface_occurrence_count(
    client: TestClient, db: Session, admin: User
) -> None:
    dedup_key = f"test:{new_id('t')}"
    for _ in range(3):
        system_log.emit(
            source=SystemLogSource.RATE_LIMIT,
            event="test.count",
            level=SystemLogLevel.WARNING,
            message="rate limited",
            dedup_key=dedup_key,
        )

    row = db.scalar(select(SystemLog).where(SystemLog.dedup_key == dedup_key))
    assert row is not None

    body = client.get(
        "/v1/admin/logs",
        params={"source": "rate_limit", "q": "test.count"},
        headers=admin_header(admin),
    ).json()
    match = next(item for item in body["items"] if item["id"] == row.id)
    assert match["occurrence_count"] is not None
    assert match["occurrence_count"] >= 1
