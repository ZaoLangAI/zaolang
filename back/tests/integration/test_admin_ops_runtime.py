"""Runtime operations: system health, job forensics, routing and agent runs."""

from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents import router
from app.domain.credits import service as credits_service
from app.domain.jobs import async_tasks
from app.domain.jobs import service as jobs_service
from app.domain.jobs import state_machine as sm
from app.domain.workflow_templates import service as workflow_templates_service
from app.models import AuditLog, GenerationJob, ProviderAttempt, User
from app.models.base import new_id, utcnow
from app.models.enums import JobStatus, Operation, ProviderAttemptStatus, ProviderKind, QualityTier
from app.providers.base import GenerationRequest, GenerationResult, ProviderCapability
from app.workers import pipeline
from app.workflows.defaults import default_graph
from tests.conftest import admin_header

pytestmark = pytest.mark.usefixtures("fake_media_catalog")


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


class _PendingAdminTestProvider:
    """A render that never settles on its own — only `terminate` or a poll
    tick moves it forward. `submit`/`poll` both stay pending forever, which
    is exactly the shape `terminate` must handle without waiting on it."""

    name = "async_video_admin_test"
    kind = ProviderKind.COMMERCIAL_API

    def __init__(self) -> None:
        self.cancelled: list[str] = []

    def submit(self, request: GenerationRequest) -> GenerationResult:
        return GenerationResult(succeeded=False, pending=True, external_task_id="ext_admin_1")

    def poll(self, external_task_id: str, request: GenerationRequest) -> GenerationResult:
        return GenerationResult(succeeded=False, pending=True, external_task_id=external_task_id)

    def cancel(self, external_task_id: str) -> bool:
        self.cancelled.append(external_task_id)
        return True


@pytest.fixture
def suspended_video_job(
    db: Session, funded: User, monkeypatch: pytest.MonkeyPatch
) -> tuple[GenerationJob, _PendingAdminTestProvider]:
    """A `RUNNING` job parked on an `AsyncProviderTask`, the scenario
    `terminate` must synchronously notify the provider about."""
    instance = _PendingAdminTestProvider()
    monkeypatch.setattr(
        router,
        "build_catalog",
        lambda session: {
            instance.name: ProviderCapability(
                name=instance.name,
                kind=ProviderKind.COMMERCIAL_API,
                operations=frozenset({Operation.TEXT_TO_VIDEO}),
                tiers=frozenset({QualityTier.STANDARD}),
                quality_prior=0.9,
                typical_latency_ms=60_000,
                unit_cost_micro_usd=200000,
                model_or_workflow="minimax-h3",
                provider_factory=lambda: instance,
            )
        },
    )
    result = jobs_service.submit(
        db,
        user_id=funded.id,
        operation=Operation.TEXT_TO_VIDEO,
        quality_tier=QualityTier.STANDARD,
        params={"prompt": "运维终止用例", "aspect_ratio": "16:9", "duration_seconds": 5},
        idempotency_key=new_id("idk"),
    )
    outcome = pipeline.run_generation_pipeline(db, result.job.id)
    assert outcome.status == JobStatus.RUNNING
    db.commit()
    job = db.get(GenerationJob, result.job.id)
    assert job is not None
    return job, instance


# --- system health --------------------------------------------------------


def test_health_reports_every_dependency(client: TestClient, admin: User) -> None:
    body = client.get("/v1/admin/health", headers=admin_header(admin)).json()
    assert {s["name"] for s in body["services"]} == {
        "postgres",
        "redis",
        "minio",
        "celery",
        "async_provider_polling",
    }


def test_health_reports_gateway_reachability_as_false_without_configured_endpoints(
    client: TestClient, admin: User
) -> None:
    """An operator debugging odd agent output needs to know whether the
    platform is talking to a real gateway at all. `probe()` always makes a
    real connectivity check now (no stub short-circuit), so with no
    `/admin/models` endpoint configured it reports unreachable."""
    body = client.get("/v1/admin/health", headers=admin_header(admin)).json()
    assert body["llm_reachable"] is False


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


def test_health_does_not_flag_a_task_still_within_its_poll_window(
    client: TestClient,
    admin: User,
    suspended_video_job: tuple[GenerationJob, _PendingAdminTestProvider],
) -> None:
    """A task suspended moments ago is not evidence of a dead Beat."""
    body = client.get("/v1/admin/health", headers=admin_header(admin)).json()
    probe = next(s for s in body["services"] if s["name"] == "async_provider_polling")
    assert probe["healthy"] is True


def test_health_flags_an_async_task_nobody_has_polled_in_a_while(
    client: TestClient,
    db: Session,
    admin: User,
    suspended_video_job: tuple[GenerationJob, _PendingAdminTestProvider],
) -> None:
    """`_ping_celery` only proves the broker is reachable and an empty queue
    looks identical whether Beat is idle or dead. This probe has to catch the
    case a stopped Beat actually causes: real suspended work with nobody
    coming back for it — the exact shape of `job_01kzwxrzb20h8gdqhavns763ww`."""
    job, _provider = suspended_video_job
    task = async_tasks.find_for_job(db, job.id)
    assert task is not None
    task.next_poll_at = utcnow() - dt.timedelta(seconds=async_tasks.POLL_INTERVAL_SECONDS * 10)
    db.commit()

    body = client.get("/v1/admin/health", headers=admin_header(admin)).json()
    probe = next(s for s in body["services"] if s["name"] == "async_provider_polling")
    assert probe["healthy"] is False
    assert "1 个异步供应商任务" in probe["detail"]


def test_the_declared_workflow_is_available_for_the_timeline(
    client: TestClient, admin: User
) -> None:
    body = client.get(
        "/v1/admin/workflow",
        params={"operation": "text_to_image"},
        headers=admin_header(admin),
    ).json()
    assert body["steps"][0]["node_type"] == "safety_check"
    # No template id was passed and nothing has been published in this test,
    # so this is the code-level fallback, not anything a real job pinned.
    assert body["is_pinned"] is False


def test_pipeline_shape_follows_the_jobs_pinned_template_not_the_latest_publish(
    client: TestClient, db: Session, admin: User, funded: User, author: User
) -> None:
    """A job must keep describing the graph it actually ran, even after an
    operator republishes a newer version for the operation afterwards —
    `GenerationJob.workflow_template_id` is pinned once and never moves."""
    v1 = workflow_templates_service.publish(
        db,
        operation=Operation.TEXT_TO_IMAGE.value,
        name="v1",
        graph_json=default_graph(db),
        actor_user_id=author.id,
        reason="v1",
    )
    db.commit()

    result = jobs_service.submit(
        db,
        user_id=funded.id,
        operation=Operation.TEXT_TO_IMAGE,
        quality_tier=QualityTier.STANDARD,
        params={"prompt": "锁定版本回放"},
        idempotency_key=new_id("idk"),
    )
    pipeline.run_generation_pipeline(db, result.job.id)
    db.commit()
    job = db.get(GenerationJob, result.job.id)
    assert job is not None
    assert job.workflow_template_id == v1.id

    workflow_templates_service.publish(
        db,
        operation=Operation.TEXT_TO_IMAGE.value,
        name="v2",
        graph_json=default_graph(db),
        actor_user_id=author.id,
        reason="发布新版本",
    )
    db.commit()

    pinned = client.get(
        "/v1/admin/workflow",
        params={"operation": "text_to_image", "template_id": job.workflow_template_id},
        headers=admin_header(admin),
    ).json()
    assert pinned["version"] == 1
    assert pinned["is_pinned"] is True

    current = client.get(
        "/v1/admin/workflow",
        params={"operation": "text_to_image"},
        headers=admin_header(admin),
    ).json()
    assert current["version"] == 2
    assert current["is_pinned"] is False

    detail = client.get(f"/v1/admin/jobs/{job.id}", headers=admin_header(admin)).json()
    assert detail["workflow_template_id"] == v1.id

    list_body = client.get("/v1/admin/jobs", headers=admin_header(admin)).json()
    row = next(j for j in list_body["items"] if j["id"] == job.id)
    assert row["workflow_template_id"] == v1.id


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


def test_jobs_can_be_filtered_by_several_statuses_at_once(
    client: TestClient, admin: User, finished_job: GenerationJob, queued_job: GenerationJob
) -> None:
    """The console's status filter is a multiselect: values are joined into
    one comma-separated query value rather than repeated query params."""
    body = client.get(
        "/v1/admin/jobs",
        params={"status": f"{JobStatus.SUCCEEDED.value},{JobStatus.CREATED.value}"},
        headers=admin_header(admin),
    ).json()
    ids = [j["id"] for j in body["items"]]
    assert finished_job.id in ids
    assert queued_job.id in ids


def test_an_unknown_status_value_is_rejected(client: TestClient, admin: User) -> None:
    response = client.get(
        "/v1/admin/jobs", params={"status": "not_a_real_status"}, headers=admin_header(admin)
    )
    assert response.status_code == 422


def test_jobs_can_be_filtered_by_user_id_substring(
    client: TestClient, admin: User, funded: User, finished_job: GenerationJob
) -> None:
    """Pasting a raw (partial) `user_id` still has to work — an operator may
    only have that on hand, copied from a log line or a credit ledger row."""
    body = client.get(
        "/v1/admin/jobs", params={"user": funded.id}, headers=admin_header(admin)
    ).json()
    assert all(j["user_id"] == funded.id for j in body["items"])


def test_jobs_can_be_filtered_by_fuzzy_username_or_display_name(
    client: TestClient, admin: User, funded: User, finished_job: GenerationJob
) -> None:
    handle_body = client.get(
        "/v1/admin/jobs",
        params={"user": funded.profile.handle[:3]},
        headers=admin_header(admin),
    ).json()
    assert finished_job.id in [j["id"] for j in handle_body["items"]]

    display_name_body = client.get(
        "/v1/admin/jobs",
        params={"user": funded.profile.display_name[:2]},
        headers=admin_header(admin),
    ).json()
    assert finished_job.id in [j["id"] for j in display_name_body["items"]]

    no_hit_body = client.get(
        "/v1/admin/jobs",
        params={"user": "找不到的用户名字符串xyz"},
        headers=admin_header(admin),
    ).json()
    assert finished_job.id not in [j["id"] for j in no_hit_body["items"]]


def test_job_detail_replays_the_whole_chain(
    client: TestClient, admin: User, finished_job: GenerationJob
) -> None:
    """Diagnosing a bad run means seeing the events, the provider attempts and
    the agent reasoning together."""
    body = client.get(f"/v1/admin/jobs/{finished_job.id}", headers=admin_header(admin)).json()
    assert body["events"]
    assert body["attempts"]
    assert body["agent_runs"]


def test_job_detail_surfaces_provider_error_detail(
    client: TestClient, db: Session, admin: User, queued_job: GenerationJob
) -> None:
    """Ops needs the HTTP/timeout body, not just the public failure sentence.

    Providers persist that text under `raw_metadata_redacted_json.detail`;
    reading `.error` instead left `error_message` empty on every real
    failure the console is meant to explain.
    """
    sm.transition(
        db,
        queued_job.id,
        JobStatus.FAILED,
        failure_code="PROVIDER_INVALID_RESPONSE",
        failure_message="生成失败，积分已退回。",
    )
    db.add(
        ProviderAttempt(
            job_id=queued_job.id,
            provider="ep_test:text_to_image",
            model_or_workflow_version="test-model",
            attempt_number=1,
            status=ProviderAttemptStatus.FAILED,
            failure_code="PROVIDER_INVALID_RESPONSE",
            raw_metadata_redacted_json={
                "provider": "aihubmix",
                "detail": "HTTP 400: image size is invalid",
            },
            created_at=utcnow(),
        )
    )
    db.commit()

    body = client.get(f"/v1/admin/jobs/{queued_job.id}", headers=admin_header(admin)).json()
    assert body["failure_code"] == "PROVIDER_INVALID_RESPONSE"
    assert body["failure_message"] == "生成失败，积分已退回。"
    assert body["attempts"]
    assert body["attempts"][0]["error_code"] == "PROVIDER_INVALID_RESPONSE"
    assert body["attempts"][0]["error_message"] == "HTTP 400: image size is invalid"


def test_job_summaries_resolve_names_instead_of_raw_ids(
    client: TestClient, admin: User, funded: User, finished_job: GenerationJob
) -> None:
    """Raw ids (`usr_...`, `fake_paid_api:...`) must never be the only thing
    an operator sees — a display name/handle/provider label always come
    back alongside them when resolvable."""
    list_body = client.get("/v1/admin/jobs", headers=admin_header(admin)).json()
    row = next(j for j in list_body["items"] if j["id"] == finished_job.id)
    assert row["user_id"] == funded.id
    assert row["user_display_name"] == funded.profile.display_name
    assert row["user_handle"] == funded.profile.handle

    detail = client.get(f"/v1/admin/jobs/{finished_job.id}", headers=admin_header(admin)).json()
    assert detail["user_display_name"] == funded.profile.display_name
    assert any(run["agent_name"] for run in detail["agent_runs"])
    assert all("node_id" in event for event in detail["events"])


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


def test_job_detail_surfaces_an_in_flight_async_task(
    client: TestClient,
    admin: User,
    suspended_video_job: tuple[GenerationJob, _PendingAdminTestProvider],
) -> None:
    """The one place the ops console can see what a `RUNNING` job with no
    Celery task in flight is actually waiting on."""
    job, _provider = suspended_video_job
    body = client.get(f"/v1/admin/jobs/{job.id}", headers=admin_header(admin)).json()
    assert body["async_task"] is not None
    assert body["async_task"]["external_task_id"] == "ext_admin_1"
    assert body["async_task"]["capability_name"] == "async_video_admin_test"


def test_terminating_a_job_with_an_in_flight_async_task_notifies_the_provider(
    client: TestClient,
    db: Session,
    admin: User,
    suspended_video_job: tuple[GenerationJob, _PendingAdminTestProvider],
) -> None:
    """The behaviour this whole feature exists for: an operator forcing a
    job that is still rendering upstream must not leave the provider
    unaware, waiting on a poll tick that will never come because the job is
    already terminal."""
    job, provider = suspended_video_job

    response = client.post(
        f"/v1/admin/jobs/{job.id}/terminate",
        json={"reason": "供应商长时间无响应", "confirm": True, "release_credits": True},
        headers=admin_header(admin),
    )
    assert response.status_code == 200, response.text
    assert provider.cancelled == ["ext_admin_1"]
    assert async_tasks.find_for_job(db, job.id) is None

    entry = db.scalar(
        select(AuditLog).where(
            AuditLog.action == "job.force_terminate", AuditLog.target_id == job.id
        )
    )
    assert entry is not None
    assert entry.after_json["upstream_cancel_attempted"] is True
    assert entry.after_json["upstream_cancel_succeeded"] is True


def test_terminating_a_job_without_an_async_task_behaves_as_before(
    client: TestClient, db: Session, admin: User, queued_job: GenerationJob
) -> None:
    """The new branch must be a no-op for the common case: no in-flight
    external task to notify."""
    response = client.post(
        f"/v1/admin/jobs/{queued_job.id}/terminate",
        json={"reason": "运营人员误提交", "confirm": True, "release_credits": True},
        headers=admin_header(admin),
    )
    assert response.status_code == 200, response.text

    entry = db.scalar(
        select(AuditLog).where(
            AuditLog.action == "job.force_terminate", AuditLog.target_id == queued_job.id
        )
    )
    assert entry is not None
    assert entry.after_json["upstream_cancel_attempted"] is False
    assert entry.after_json["upstream_cancel_succeeded"] is None


# --- provider and agent operations ---------------------------------------


def test_provider_stats_are_reported(
    client: TestClient, admin: User, finished_job: GenerationJob
) -> None:
    body = client.get("/v1/admin/providers/stats", headers=admin_header(admin)).json()
    assert body["items"]
    for item in body["items"]:
        assert 0.0 <= item["success_rate"] <= 1.0


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
    import datetime as dt

    from app.models.base import utcnow

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
