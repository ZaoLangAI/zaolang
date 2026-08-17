"""Live notification push: publish-on-write and the SSE stream endpoint."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.v1 import community
from app.domain.credits import service as credits_service
from app.domain.jobs import service as jobs_service
from app.domain.jobs import state_machine as sm
from app.domain.notifications import push as notifications
from app.models import User
from app.models.base import new_id
from app.models.enums import JobStatus, NotificationType, Operation, QualityTier
from app.realtime import publisher
from tests.conftest import auth_header

pytestmark = pytest.mark.usefixtures("fake_media_catalog")


@pytest.fixture
def recorded_publishes(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, object]]]:
    """Captures every `publisher.publish_notification` call without touching Redis."""
    calls: list[tuple[str, dict[str, object]]] = []

    def fake_publish(user_id: str, payload: dict[str, object]) -> None:
        calls.append((user_id, payload))

    monkeypatch.setattr(notifications.publisher, "publish_notification", fake_publish)
    return calls


def test_notify_publishes_to_the_users_channel(
    db: Session, author: User, recorded_publishes: list[tuple[str, dict[str, object]]]
) -> None:
    record = notifications.notify(
        db,
        user_id=author.id,
        type=NotificationType.SYSTEM,
        title_key="notification.announcement",
        payload={"headline": "test"},
    )

    assert len(recorded_publishes) == 1
    user_id, payload = recorded_publishes[0]
    assert user_id == author.id
    assert payload["id"] == record.id
    assert payload["type"] == NotificationType.SYSTEM
    assert payload["title_key"] == "notification.announcement"
    assert payload["payload"] == {"headline": "test"}
    assert payload["read"] is False
    assert "created_at" in payload and "updated_at" in payload


def test_job_transitions_publish_the_same_notification_id_each_time(
    db: Session, author: User, recorded_publishes: list[tuple[str, dict[str, object]]]
) -> None:
    credits_service.grant(db, author.id, 5_000, idempotency_key=new_id("grant"))
    job = jobs_service.submit(
        db,
        user_id=author.id,
        operation=Operation.TEXT_TO_IMAGE,
        quality_tier=QualityTier.STANDARD,
        params={"prompt": "深夜的港口", "aspect_ratio": "16:9"},
        idempotency_key=new_id("idk"),
    ).job

    sm.transition(db, job.id, JobStatus.QUEUED)
    sm.transition(db, job.id, JobStatus.RUNNING)
    sm.transition(db, job.id, JobStatus.SUCCEEDED)

    # One publish for the initial `notify`-free creation notification plus one
    # per transition — every one of them must carry the same notification id,
    # since the row is upserted in place rather than recreated.
    assert len(recorded_publishes) >= 4
    ids = {payload["id"] for _, payload in recorded_publishes}
    assert len(ids) == 1
    assert recorded_publishes[-1][1]["title_key"] == "notification.job_succeeded"
    assert recorded_publishes[-1][1]["payload"]["status"] == JobStatus.SUCCEEDED


def test_stream_requires_auth(client: TestClient) -> None:
    assert client.get("/v1/notifications/stream").status_code == 401


def test_stream_returns_an_event_stream(
    client: TestClient, author: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Bounds the connection to a near-instant lifetime so this test does not
    # block on the real 10-minute cap; the stream has no terminal condition of
    # its own the way a job's does, so the test has to impose one.
    monkeypatch.setattr(community, "NOTIFICATION_STREAM_MAX_DURATION_SECONDS", 0.01)
    monkeypatch.setattr(publisher, "SUBSCRIBE_TIMEOUT_SECONDS", 0.05)

    response = client.get("/v1/notifications/stream", headers=auth_header(author))
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
