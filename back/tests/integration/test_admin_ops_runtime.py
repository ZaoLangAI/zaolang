"""Runtime operations: system health, job forensics, routing and agent runs."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.credits import service as credits_service
from app.domain.jobs import service as jobs_service
from app.models import AuditLog, GenerationJob, User
from app.models.base import new_id
from app.models.enums import JobStatus, Operation, QualityTier
from app.workers import pipeline
from tests.conftest import admin_header


@pytest.fixture
def funded(db: Session, author: User) -> User:
    credits_service.grant(db, author.id, 5_000, idempotency_key=new_id("grant"))
    db.flush()
    return author


@pytest.fixture
def finished_job(db: Session, funded: User) -> GenerationJob:
    result = jobs_service.submit(
        db,
        user_id=funded.id,
        operation=Operation.TEXT_TO_IMAGE,
        quality_tier=QualityTier.STANDARD,
        params={"prompt": "运维回放用例"},
        idempotency_key=new_id("idk"),
    )
    pipeline.run_generation_pipeline(db, result.job.id)
    db.commit()
    return db.get(GenerationJob, result.job.id)  # type: ignore[return-value]


@pytest.fixture
def queued_job(db: Session, funded: User) -> GenerationJob:
    result = jobs_service.submit(
        db,
        user_id=funded.id,
        operation=Operation.TEXT_TO_IMAGE,
        quality_tier=QualityTier.STANDARD,
        params={"prompt": "卡住的任务"},
        idempotency_key=new_id("idk"),
    )
    db.commit()
    return result.job


# --- system health --------------------------------------------------------


def test_health_reports_every_dependency(client: TestClient, admin: User) -> None:
    body = client.get("/v1/admin/health", headers=admin_header(admin)).json()
    assert {s["name"] for s in body["services"]} == {"postgres", "redis", "minio", "celery"}


def test_health_reports_the_running_llm_mode(client: TestClient, admin: User) -> None:
    """An operator debugging odd agent output needs to know whether the
    platform is talking to a real gateway at all."""
    body = client.get("/v1/admin/health", headers=admin_header(admin)).json()
    assert body["llm_mode"] == "stub"


def test_stub_mode_reports_gateway_reachability_as_not_applicable(
    client: TestClient, admin: User
) -> None:
    body = client.get("/v1/admin/health", headers=admin_header(admin)).json()
    assert body["llm_reachable"] is None


def test_health_lists_every_queue(client: TestClient, admin: User) -> None:
    from app.workers.celery_app import QUEUE_NAMES

    body = client.get("/v1/admin/health", headers=admin_header(admin)).json()
    assert {q["queue"] for q in body["queues"]} == set(QUEUE_NAMES)


def test_health_survives_a_dependency_being_down(
    client: TestClient, admin: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The page has to load precisely when something is broken."""
    from app.api.v1.admin import observability

    def broken() -> None:
        raise RuntimeError("minio unreachable")

    monkeypatch.setattr(observability, "_ping_storage", broken)

    response = client.get("/v1/admin/health", headers=admin_header(admin))
    assert response.status_code == 200
    minio = next(s for s in response.json()["services"] if s["name"] == "minio")
    assert minio["healthy"] is False
    assert "minio unreachable" in minio["detail"]


def test_a_failing_probe_does_not_break_the_rest_of_the_report(
    client: TestClient, admin: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api.v1.admin import observability

    monkeypatch.setattr(
        observability, "_ping_redis", lambda: (_ for _ in ()).throw(RuntimeError("down"))
    )

    body = client.get("/v1/admin/health", headers=admin_header(admin)).json()
    postgres = next(s for s in body["services"] if s["name"] == "postgres")
    assert postgres["healthy"] is True


def test_the_declared_workflow_is_available_for_the_timeline(
    client: TestClient, admin: User
) -> None:
    body = client.get(
        "/v1/admin/workflow",
        params={"operation": "text_to_image"},
        headers=admin_header(admin),
    ).json()
    assert body["steps"][0]["node_type"] == "safety_check"


# --- job forensics --------------------------------------------------------


def test_jobs_can_be_listed(client: TestClient, admin: User, finished_job: GenerationJob) -> None:
    body = client.get("/v1/admin/jobs", headers=admin_header(admin)).json()
    assert finished_job.id in [j["id"] for j in body["items"]]


def test_jobs_can_be_filtered_by_status(
    client: TestClient, admin: User, finished_job: GenerationJob, queued_job: GenerationJob
) -> None:
    body = client.get(
        "/v1/admin/jobs", params={"status": JobStatus.SUCCEEDED.value}, headers=admin_header(admin)
    ).json()
    ids = [j["id"] for j in body["items"]]
    assert finished_job.id in ids
    assert queued_job.id not in ids


def test_jobs_can_be_filtered_by_user(
    client: TestClient, admin: User, funded: User, finished_job: GenerationJob
) -> None:
    body = client.get(
        "/v1/admin/jobs", params={"user_id": funded.id}, headers=admin_header(admin)
    ).json()
    assert all(j["user_id"] == funded.id for j in body["items"])


def test_job_detail_replays_the_whole_chain(
    client: TestClient, admin: User, finished_job: GenerationJob
) -> None:
    """Diagnosing a bad run means seeing the events, the provider attempts and
    the agent reasoning together."""
    body = client.get(f"/v1/admin/jobs/{finished_job.id}", headers=admin_header(admin)).json()
    assert body["events"]
    assert body["attempts"]
    assert body["agent_runs"]


def test_job_events_come_back_in_order(
    client: TestClient, admin: User, finished_job: GenerationJob
) -> None:
    body = client.get(
        f"/v1/admin/jobs/{finished_job.id}/events", headers=admin_header(admin)
    ).json()
    sequences = [e["sequence"] for e in body["items"]]
    assert sequences == sorted(sequences)


def test_an_unknown_job_is_a_clean_404(client: TestClient, admin: User) -> None:
    assert client.get("/v1/admin/jobs/job_missing", headers=admin_header(admin)).status_code == 404


def test_routing_replay_shows_every_candidate_with_a_verdict(
    client: TestClient, admin: User, finished_job: GenerationJob
) -> None:
    body = client.get(
        f"/v1/admin/jobs/{finished_job.id}/routing", headers=admin_header(admin)
    ).json()
    assert body["chosen_provider"]
    assert body["candidates"]
    for candidate in body["candidates"]:
        assert candidate["eligible"] or candidate["filter_reason"]


def test_forcing_a_job_to_terminate_requires_confirmation(
    client: TestClient, admin: User, queued_job: GenerationJob
) -> None:
    response = client.post(
        f"/v1/admin/jobs/{queued_job.id}/terminate",
        json={"reason": "卡死处理", "confirm": False, "release_credits": True},
        headers=admin_header(admin),
    )
    assert response.status_code == 422


def test_forcing_a_job_to_terminate_requires_a_reason(
    client: TestClient, admin: User, queued_job: GenerationJob
) -> None:
    response = client.post(
        f"/v1/admin/jobs/{queued_job.id}/terminate",
        json={"reason": "", "confirm": True, "release_credits": True},
        headers=admin_header(admin),
    )
    assert response.status_code == 422


def test_forcing_a_job_to_terminate_releases_the_reservation(
    client: TestClient, db: Session, admin: User, funded: User, queued_job: GenerationJob
) -> None:
    """Credits held by a job nobody will finish must go back to the user."""
    reserved_before = credits_service.get_or_create_account(db, funded.id).reserved_balance
    assert reserved_before > 0

    response = client.post(
        f"/v1/admin/jobs/{queued_job.id}/terminate",
        json={"reason": "供应商长时间无响应", "confirm": True, "release_credits": True},
        headers=admin_header(admin),
    )
    assert response.status_code == 200, response.text

    account = credits_service.get_or_create_account(db, funded.id)
    assert account.reserved_balance == 0


def test_forcing_a_job_to_terminate_is_audited(
    client: TestClient, db: Session, admin: User, queued_job: GenerationJob
) -> None:
    client.post(
        f"/v1/admin/jobs/{queued_job.id}/terminate",
        json={"reason": "供应商长时间无响应", "confirm": True, "release_credits": True},
        headers=admin_header(admin),
    )
    entry = db.scalar(
        select(AuditLog).where(
            AuditLog.action == "job.force_terminate", AuditLog.target_id == queued_job.id
        )
    )
    assert entry is not None
    assert entry.reason == "供应商长时间无响应"


def test_a_finished_job_cannot_be_force_terminated(
    client: TestClient, admin: User, finished_job: GenerationJob
) -> None:
    """Terminal states are final; reopening one would let a settled job be
    settled twice."""
    response = client.post(
        f"/v1/admin/jobs/{finished_job.id}/terminate",
        json={"reason": "误操作", "confirm": True, "release_credits": True},
        headers=admin_header(admin),
    )
    assert response.status_code in (409, 422)


def test_a_reviewer_cannot_force_terminate_a_job(
    client: TestClient, reviewer: User, queued_job: GenerationJob
) -> None:
    response = client.post(
        f"/v1/admin/jobs/{queued_job.id}/terminate",
        json={"reason": "越权尝试", "confirm": True, "release_credits": True},
        headers=admin_header(reviewer),
    )
    assert response.status_code == 403


# --- provider and agent operations ---------------------------------------


def test_provider_stats_are_reported(
    client: TestClient, admin: User, finished_job: GenerationJob
) -> None:
    body = client.get("/v1/admin/providers/stats", headers=admin_header(admin)).json()
    assert body["items"]
    for item in body["items"]:
        assert 0.0 <= item["success_rate"] <= 1.0


def test_agent_runs_are_listed(
    client: TestClient, admin: User, finished_job: GenerationJob
) -> None:
    body = client.get("/v1/admin/agent-runs", headers=admin_header(admin)).json()
    assert body["items"]


def test_agent_runs_can_be_filtered_to_one_job(
    client: TestClient, admin: User, finished_job: GenerationJob
) -> None:
    body = client.get(
        "/v1/admin/agent-runs", params={"job_id": finished_job.id}, headers=admin_header(admin)
    ).json()
    assert body["items"]
    assert all(run["job_id"] == finished_job.id for run in body["items"])


def test_degraded_runs_can_be_isolated(
    client: TestClient, admin: User, finished_job: GenerationJob
) -> None:
    """Finding out how often the gateway fell back to the stub is the point of
    recording it."""
    body = client.get(
        "/v1/admin/agent-runs", params={"degraded_only": True}, headers=admin_header(admin)
    ).json()
    assert all(run["degraded"] for run in body["items"])


def test_agent_usage_is_summarised_per_agent(
    client: TestClient, admin: User, finished_job: GenerationJob
) -> None:
    body = client.get("/v1/admin/agent-runs/usage", headers=admin_header(admin)).json()
    assert body["items"]
    for item in body["items"]:
        assert item["runs"] >= item["degraded_runs"]


def test_job_stats_reports_status_and_operation_mix(
    client: TestClient, admin: User, finished_job: GenerationJob
) -> None:
    body = client.get("/v1/admin/jobs/stats", headers=admin_header(admin)).json()
    assert body["total_jobs"] >= 1
    assert body["by_status"].get(JobStatus.SUCCEEDED.value, 0) >= 1
    assert body["by_operation"].get(finished_job.operation, 0) >= 1
    assert body["avg_completion_ms"] is not None


def test_job_stats_window_excludes_jobs_outside_it(
    client: TestClient, db: Session, admin: User, finished_job: GenerationJob
) -> None:
    from app.models.base import utcnow
    import datetime as dt

    finished_job.created_at = utcnow() - dt.timedelta(hours=48)
    db.flush()
    db.commit()

    body = client.get(
        "/v1/admin/jobs/stats", params={"hours": 24}, headers=admin_header(admin)
    ).json()
    assert body["total_jobs"] == 0


def test_runtime_operations_are_closed_to_anonymous_callers(client: TestClient) -> None:
    for path in (
        "/v1/admin/health",
        "/v1/admin/jobs",
        "/v1/admin/jobs/stats",
        "/v1/admin/providers/stats",
    ):
        assert client.get(path).status_code == 401, path
