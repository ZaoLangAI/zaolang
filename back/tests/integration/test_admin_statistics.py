"""Daily time-series statistics for the back-office analytics module."""

from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.domain.credits import service as credits_service
from app.domain.jobs import service as jobs_service
from app.models import GenerationJob, User, Work
from app.models.base import new_id, utcnow
from app.models.enums import Operation, QualityTier
from app.workers import pipeline
from tests.conftest import admin_header

pytestmark = pytest.mark.usefixtures("fake_media_catalog")


@pytest.fixture
def funded(db: Session, author: User) -> User:
    credits_service.grant(db, author.id, 5_000, idempotency_key=new_id("grant"))
    db.flush()
    return author


@pytest.fixture
def finished_job(db: Session, funded: User) -> GenerationJob:
    """A real, fully-run job — the same fixture shape used in
    `test_admin_ops_runtime.py`, so it seeds a `GenerationJob`, a
    `ProviderAttempt`, at least one `AgentRun` and a matched
    RESERVE/CAPTURE ledger pair, all stamped "now"."""
    result = jobs_service.submit(
        db,
        user_id=funded.id,
        operation=Operation.TEXT_TO_IMAGE,
        quality_tier=QualityTier.STANDARD,
        params={"prompt": "统计模块时间序列用例"},
        idempotency_key=new_id("idk"),
    )
    pipeline.run_generation_pipeline(db, result.job.id)
    db.commit()
    return db.get(GenerationJob, result.job.id)  # type: ignore[return-value]


# --- jobs --------------------------------------------------------------


def test_jobs_timeseries_has_one_point_per_requested_day(
    client: TestClient, admin: User, finished_job: GenerationJob
) -> None:
    body = client.get(
        "/v1/admin/statistics/jobs", params={"days": 7}, headers=admin_header(admin)
    ).json()
    assert body["window_days"] == 7
    assert len(body["points"]) == 7
    assert body["points"][-1]["date"] == utcnow().date().isoformat()


def test_jobs_timeseries_counts_todays_job(
    client: TestClient, admin: User, finished_job: GenerationJob
) -> None:
    body = client.get(
        "/v1/admin/statistics/jobs", params={"days": 7}, headers=admin_header(admin)
    ).json()
    today = body["points"][-1]
    assert today["total"] >= 1
    assert today["succeeded"] >= 1
    assert today["avg_completion_ms"] is not None


def test_jobs_timeseries_fills_empty_days_with_zero(
    client: TestClient, admin: User, finished_job: GenerationJob
) -> None:
    """Only "today" has activity; every earlier day must still be a zero
    point rather than being omitted, or a line chart would misread the gap
    as missing data instead of a quiet day."""
    body = client.get(
        "/v1/admin/statistics/jobs", params={"days": 7}, headers=admin_header(admin)
    ).json()
    for point in body["points"][:-1]:
        assert point["total"] == 0
        assert point["succeeded"] == 0
        assert point["failed"] == 0
        assert point["avg_completion_ms"] is None


def test_jobs_timeseries_excludes_jobs_outside_the_window(
    client: TestClient, db: Session, admin: User, finished_job: GenerationJob
) -> None:
    finished_job.created_at = utcnow() - dt.timedelta(days=10)
    db.flush()
    db.commit()

    body = client.get(
        "/v1/admin/statistics/jobs", params={"days": 7}, headers=admin_header(admin)
    ).json()
    assert sum(point["total"] for point in body["points"]) == 0


# --- providers & agents --------------------------------------------------


def test_providers_timeseries_counts_todays_attempt(
    client: TestClient, admin: User, finished_job: GenerationJob
) -> None:
    body = client.get(
        "/v1/admin/statistics/providers", params={"days": 7}, headers=admin_header(admin)
    ).json()
    today = body["points"][-1]
    assert today["attempts"] >= 1
    assert today["successes"] >= 1
    assert today["avg_latency_ms"] is not None


def test_agents_timeseries_counts_todays_run(
    client: TestClient, admin: User, finished_job: GenerationJob
) -> None:
    body = client.get(
        "/v1/admin/statistics/agents", params={"days": 7}, headers=admin_header(admin)
    ).json()
    today = body["points"][-1]
    assert today["runs"] >= 1


# --- credits --------------------------------------------------------------


def test_credits_timeseries_counts_todays_grant_and_capture(
    client: TestClient, admin: User, finished_job: GenerationJob
) -> None:
    body = client.get(
        "/v1/admin/statistics/credits", params={"days": 7}, headers=admin_header(admin)
    ).json()
    today = body["points"][-1]
    # `funded` grants 5,000 and the finished job settles (captures) part of
    # its reservation the same day; capture amounts are stored negative.
    assert today["granted"] >= 5_000
    assert today["captured"] <= 0
    assert today["net"] != 0


# --- content ---------------------------------------------------------------


def test_content_timeseries_counts_todays_publish(
    client: TestClient, db: Session, admin: User, author: User
) -> None:
    work = Work(owner_user_id=author.id, published_at=utcnow())
    db.add(work)
    db.flush()
    db.commit()

    body = client.get(
        "/v1/admin/statistics/content", params={"days": 7}, headers=admin_header(admin)
    ).json()
    today = body["points"][-1]
    assert today["published_works"] >= 1
    assert today["remix_edges"] == 0


# --- user growth -----------------------------------------------------------


def test_users_timeseries_counts_todays_registrations_and_snapshot(
    client: TestClient, admin: User, author: User
) -> None:
    body = client.get(
        "/v1/admin/statistics/users", params={"days": 7}, headers=admin_header(admin)
    ).json()
    today = body["points"][-1]
    # `admin` and `author` are both created "now" by their fixtures.
    assert today["new_users"] >= 2
    assert body["total_users"] >= 2
    assert body["suspended_users"] == 0


# --- authorization -----------------------------------------------------------


def test_statistics_timeseries_are_closed_to_anonymous_callers(client: TestClient) -> None:
    for path in (
        "/v1/admin/statistics/jobs",
        "/v1/admin/statistics/providers",
        "/v1/admin/statistics/agents",
        "/v1/admin/statistics/credits",
        "/v1/admin/statistics/content",
        "/v1/admin/statistics/users",
    ):
        response = client.get(path)
        assert response.status_code == 401
