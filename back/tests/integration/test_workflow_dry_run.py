"""Product sandbox try-it: a real GenerationJob that skips the credit ledger.

Stub path (this file, CI): LLM_MODE=stub + fake media catalog. Celery dispatch
is mocked so the HTTP handler returns 202 without a broker; the pipeline is
then invoked inline, same as `test_generation_lifecycle`.

Live path with a real key is manual — not CI:

1. `make dev-api` and `make dev-worker` (including Beat).
2. `/admin/routing` → each Operation tab → 沙盒试跑. Reference ops need
   `{"reference_asset_ids":["ast_..."]}` (video duration defaults to 8s, range 4–15).
3. The right-hand panel streams node progress; a successful output lands in
   任务运维 and 内容审核 (POST_GENERATION). Credits are not charged.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    CreditLedgerEntry,
    GenerationJob,
    GenerationWorkflowTemplate,
    ModerationQueueItem,
    User,
)
from app.models.enums import JobOrigin, JobStatus, ModerationStage, Operation
from app.workers import pipeline
from tests.conftest import admin_header, auth_header

pytestmark = pytest.mark.usefixtures("fake_media_catalog")

_NO_REFERENCE = (
    Operation.TEXT_TO_IMAGE.value,
    Operation.TEXT_TO_VIDEO.value,
    Operation.AUDIO_GENERATION.value,
)


@pytest.fixture(autouse=True)
def _skip_celery(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.workers.tasks.dispatch_generation", lambda job: None)


def _sandbox_run(
    client: TestClient,
    operator: User,
    *,
    operation: str = Operation.TEXT_TO_IMAGE.value,
    prompt: str = "雨后的东京街头",
    graph: dict | None = None,
) -> str:
    payload: dict[str, object] = {"prompt": prompt}
    if graph is not None:
        payload["graph"] = graph
    response = client.post(
        f"/v1/admin/workflow-templates/{operation}/sandbox-run",
        json=payload,
        headers=admin_header(operator),
    )
    assert response.status_code == 202, response.text
    job_id = response.json()["job_id"]
    assert job_id
    return job_id


@pytest.mark.parametrize("operation", list(_NO_REFERENCE))
def test_sandbox_run_submits_a_real_job_for_every_non_reference_operation(
    client: TestClient, operator: User, db: Session, operation: str
) -> None:
    job_id = _sandbox_run(client, operator, operation=operation)
    job = db.get(GenerationJob, job_id)
    assert job is not None
    assert job.origin == JobOrigin.SANDBOX
    assert job.reserved_credits == 0
    assert job.quoted_credits > 0
    assert (
        db.scalar(
            select(func.count())
            .select_from(CreditLedgerEntry)
            .where(CreditLedgerEntry.job_id == job_id)
        )
        or 0
    ) == 0


def test_text_to_video_sandbox_run_defaults_duration_to_eight_seconds(
    client: TestClient, operator: User, db: Session
) -> None:
    """A prompt-only try-it must still be H3-routable; missing duration used
    to hard-filter every video provider as `duration_below_provider_minimum`."""
    job_id = _sandbox_run(client, operator, operation=Operation.TEXT_TO_VIDEO.value)
    job = db.get(GenerationJob, job_id)
    assert job is not None
    assert job.request_json["duration_seconds"] == 8


def test_text_to_video_sandbox_run_rejects_an_illegal_h3_duration(
    client: TestClient, operator: User
) -> None:
    response = client.post(
        "/v1/admin/workflow-templates/text_to_video/sandbox-run",
        json={
            "prompt": "创作香港街道视频",
            "params": {
                "duration_seconds": 16,
                "video_options": {"resolution": "2K"},
            },
        },
        headers=admin_header(operator),
    )
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_FAILED"
    assert "4-15" in body["error"]["message"]


def test_a_sandbox_run_walks_the_pipeline_without_touching_the_ledger(
    client: TestClient, operator: User, db: Session
) -> None:
    job_id = _sandbox_run(client, operator)
    outcome = pipeline.run_generation_pipeline(db, job_id)
    assert outcome.status == JobStatus.SUCCEEDED

    job = db.get(GenerationJob, job_id)
    assert job is not None
    assert job.origin == JobOrigin.SANDBOX
    assert job.reserved_credits == 0
    assert job.actual_credits == 0
    assert (
        db.scalar(
            select(func.count())
            .select_from(CreditLedgerEntry)
            .where(CreditLedgerEntry.job_id == job_id)
        )
        or 0
    ) == 0

    post = db.scalar(
        select(ModerationQueueItem).where(
            ModerationQueueItem.subject_type == "generation_job",
            ModerationQueueItem.subject_id == job_id,
            ModerationQueueItem.stage == ModerationStage.POST_GENERATION,
        )
    )
    assert post is not None
    assert post.reason_code == "SANDBOX_OUTPUT"

    listed = client.get("/v1/generation-jobs", headers=auth_header(operator)).json()
    assert all(item["id"] != job_id for item in listed["items"])
    hidden = client.get(f"/v1/generation-jobs/{job_id}", headers=auth_header(operator))
    assert hidden.status_code == 404

    ops = client.get(
        "/v1/admin/jobs",
        params={"origin": "sandbox"},
        headers=admin_header(operator),
    ).json()
    assert any(item["id"] == job_id for item in ops["items"])

    stream = client.get(f"/v1/admin/jobs/{job_id}/stream", headers=admin_header(operator))
    assert stream.status_code == 200
    assert stream.headers["content-type"].startswith("text/event-stream")
    assert "node_id" in stream.text


def test_a_needs_review_sandbox_run_still_enqueues_pre_generation(
    client: TestClient, operator: User, db: Session
) -> None:
    job_id = _sandbox_run(client, operator, prompt="血腥暴力的战场场景")
    pipeline.run_generation_pipeline(db, job_id)

    pre = db.scalar(
        select(ModerationQueueItem).where(
            ModerationQueueItem.subject_type == "generation_job",
            ModerationQueueItem.subject_id == job_id,
            ModerationQueueItem.stage == ModerationStage.PRE_GENERATION,
        )
    )
    assert pre is not None


def test_an_unpublished_draft_graph_leaves_the_live_template_alone(
    client: TestClient, db: Session, operator: User
) -> None:
    """The editor's edit -> run -> look loop: try a canvas edit without
    publishing it to every job."""
    from app.workflows.defaults import default_graph

    draft = default_graph(db)
    draft["nodes"] = [node for node in draft["nodes"] if node["id"] != "skill_context"]
    draft["edges"] = [
        edge for edge in draft["edges"] if "skill_context" not in (edge["from"], edge["to"])
    ]
    draft["edges"].append({"id": "draft", "from": "safety", "from_port": "pass", "to": "planning"})

    before = db.scalar(
        select(GenerationWorkflowTemplate).where(
            GenerationWorkflowTemplate.operation == "text_to_image",
            GenerationWorkflowTemplate.is_active.is_(True),
        )
    )
    job_id = _sandbox_run(client, operator, graph=draft)
    job = db.get(GenerationJob, job_id)
    assert job is not None
    assert job.graph_override_json is not None
    assert job.workflow_template_id is None
    assert not any(node["id"] == "skill_context" for node in job.graph_override_json["nodes"])

    pipeline.run_generation_pipeline(db, job_id)

    after = db.scalar(
        select(GenerationWorkflowTemplate).where(
            GenerationWorkflowTemplate.operation == "text_to_image",
            GenerationWorkflowTemplate.is_active.is_(True),
        )
    )
    assert (before.id if before else None) == (after.id if after else None)


def test_a_structurally_broken_draft_is_refused(client: TestClient, operator: User) -> None:
    """Held to the same validation as a publish."""
    response = client.post(
        "/v1/admin/workflow-templates/text_to_image/sandbox-run",
        json={
            "prompt": "雨后的东京街头",
            "graph": {"nodes": [{"id": "a", "type": "safety_check", "config": {}}], "edges": []},
        },
        headers=admin_header(operator),
    )
    assert response.status_code == 422


def test_repeating_a_sandbox_run_with_the_same_idempotency_key_replays(
    client: TestClient, operator: User, db: Session
) -> None:
    headers = {**admin_header(operator), "Idempotency-Key": "idk-sandbox-replay"}
    first = client.post(
        "/v1/admin/workflow-templates/text_to_image/sandbox-run",
        json={"prompt": "雨后的东京街头"},
        headers=headers,
    )
    second = client.post(
        "/v1/admin/workflow-templates/text_to_image/sandbox-run",
        json={"prompt": "雨后的东京街头"},
        headers=headers,
    )
    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["job_id"] == second.json()["job_id"]
    assert (
        db.scalar(
            select(func.count())
            .select_from(GenerationJob)
            .where(GenerationJob.user_id == operator.id, GenerationJob.origin == JobOrigin.SANDBOX)
        )
        or 0
    ) == 1


def test_a_sandbox_planning_follow_up_is_answerable_through_admin_api(
    client: TestClient, operator: User, db: Session
) -> None:
    """Text-to-image's default graph parks on the planner's clarify slot.

    C-end `/generation-jobs/{id}/input-request` 404s sandbox jobs; the
    editor answers through `/v1/admin/jobs/{id}/input-request` + `/answer`.
    """
    from app.llm.stub import PLANNER_CLARIFY_MARKER

    job_id = _sandbox_run(client, operator, prompt=f"{PLANNER_CLARIFY_MARKER}：雨后的东京街头")
    outcome = pipeline.run_generation_pipeline(db, job_id)
    assert outcome.status == JobStatus.AWAITING_INPUT

    hidden = client.get(
        f"/v1/generation-jobs/{job_id}/input-request", headers=auth_header(operator)
    )
    assert hidden.status_code == 404

    pending = client.get(f"/v1/admin/jobs/{job_id}/input-request", headers=admin_header(operator))
    assert pending.status_code == 200, pending.text
    body = pending.json()
    assert body["node_id"] == "planning"
    assert [q["id"] for q in body["questions"]] == ["subject_count", "camera"]

    answered = client.post(
        f"/v1/admin/jobs/{job_id}/answer",
        headers=admin_header(operator),
        json={"answers": [{"question_id": "subject_count", "value": "one"}]},
    )
    assert answered.status_code == 200, answered.text
    assert answered.json()["status"] == JobStatus.SUCCEEDED.value
    job = db.get(GenerationJob, job_id)
    assert job is not None
    assert job.status == JobStatus.SUCCEEDED
    assert (
        client.get(
            f"/v1/admin/jobs/{job_id}/input-request", headers=admin_header(operator)
        ).status_code
        == 404
    )
