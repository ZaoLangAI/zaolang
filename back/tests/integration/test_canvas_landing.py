"""Generated results landing back on the canvas.

The hook hangs off `state_machine.transition`, which every terminal write in
the system funnels through. That choice is what these tests are really about:
it means a *failed* job reaches the canvas too, so a placeholder flips to an
error instead of spinning forever, and it means a redelivered terminal
transition must not insert the card twice.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.domain.canvas import agent_service, graph_service
from app.domain.credits import service as credits_service
from app.domain.errors import NotFound, ValidationFailed
from app.domain.jobs import service as jobs_service
from app.domain.jobs import state_machine as sm
from app.models import (
    Asset,
    CanvasAgentRun,
    CanvasAgentTask,
    CanvasNode,
    CanvasProject,
    GenerationJob,
    JobEvent,
    User,
)
from app.models.base import new_id
from app.models.enums import (
    AssetRole,
    CanvasAgentRunStatus,
    CanvasAgentTaskStatus,
    CanvasNodeKind,
    CanvasNodeOrigin,
    JobEventType,
    JobStatus,
    MediaType,
    Operation,
    QualityTier,
)
from app.platform_config import service as config_service
from app.platform_config.schemas import FeatureFlags
from tests.factories import make_job

pytestmark = pytest.mark.usefixtures("fake_media_catalog")


@pytest.fixture(autouse=True)
def _canvas_flag(db: Session) -> None:
    """Most tests here drive `graph_service` directly, which has no flag gate.
    `restore_task_card` goes through `canvas_service.get_project`, which does —
    correctly, since it is a user action rather than a pipeline callback."""
    value = config_service.get_typed(db, "feature_flags", FeatureFlags).model_dump(mode="json")
    value.update({"canvas_studio_enabled": True})
    config_service.set_value(db, "feature_flags", value, actor_user_id=None, note="test")


def _output_asset(session: Session, owner: User) -> Asset:
    """A real row: `generation_jobs.output_asset_id` is a foreign key, so a
    made-up id would fail the transition rather than the landing."""
    asset = Asset(
        owner_user_id=owner.id,
        object_key=f"test/{new_id('obj')}.png",
        media_type=MediaType.IMAGE,
        mime_type="image/png",
        size_bytes=16,
        checksum_sha256="0" * 64,
        role=AssetRole.GENERATION_OUTPUT,
        width=8,
        height=8,
    )
    session.add(asset)
    session.flush()
    return asset


def _canvas(session: Session, owner: User) -> CanvasProject:
    project = CanvasProject(
        owner_user_id=owner.id,
        series_id=None,
        title="落卡画布",
        viewport_json={},
        change_seq=0,
        updated_by_user_id=owner.id,
    )
    session.add(project)
    session.flush()
    return project


def _agent_card(session: Session, project: CanvasProject, owner: User) -> CanvasNode:
    graph_service.apply_ops(
        session,
        canvas_id=project.id,
        user_id=owner.id,
        ops=[
            {
                "op_id": "op_agent",
                "kind": "node.create",
                "node": {
                    "id": "cnd_agent",
                    "kind": "agent",
                    "position": {"x": 0, "y": 0},
                    "data": {},
                },
            }
        ],
    )
    node = session.get(CanvasNode, "cnd_agent")
    assert node is not None
    return node


def _run_with_job(
    session: Session, owner: User, *, operation: str = Operation.TEXT_TO_IMAGE.value
) -> tuple[CanvasAgentRun, CanvasAgentTask, GenerationJob, Asset]:
    """A confirmed run with exactly one submitted task."""
    credits_service.grant(session, owner.id, 100_000, idempotency_key=new_id("grant"))
    project = _canvas(session, owner)
    node = _agent_card(session, project, owner)

    run = CanvasAgentRun(
        canvas_id=project.id,
        user_id=owner.id,
        goal="生成一张图",
        agent_node_id=node.id,
        context_node_ids_json=[node.id],
        context_digest_json={},
        plan_json={},
        status=CanvasAgentRunStatus.RUNNING.value,
    )
    session.add(run)
    session.flush()

    params = {"prompt": "雨夜街头"}
    if operation in (Operation.TEXT_TO_VIDEO.value, Operation.IMAGE_TO_VIDEO.value):
        params["duration_seconds"] = 5
    result = jobs_service.submit(
        session,
        user_id=owner.id,
        operation=operation,
        quality_tier=QualityTier.STANDARD.value,
        params=params,
        idempotency_key=new_id("idk"),
    )
    task = CanvasAgentTask(
        run_id=run.id,
        ordinal=0,
        operation=operation,
        quality_tier=QualityTier.STANDARD.value,
        request_json=params,
        generation_job_id=result.job.id,
        status=CanvasAgentTaskStatus.SUBMITTED.value,
        drop_x=400,
        drop_y=120,
    )
    session.add(task)
    session.flush()
    return run, task, result.job, _output_asset(session, owner)


def _succeed(session: Session, job: GenerationJob, asset_id: str) -> None:
    """Walk the job to SUCCEEDED through the real transitions.

    Starts at QUEUED: `jobs_service.submit` leaves the row at `created` and
    only *appends* a queued event — the move itself belongs to the worker.
    """
    sm.transition(session, job.id, JobStatus.QUEUED)
    sm.transition(session, job.id, JobStatus.SUBMITTED)
    sm.transition(session, job.id, JobStatus.RUNNING)
    sm.transition(session, job.id, JobStatus.SUCCEEDED, output_asset_id=asset_id)


def test_a_succeeded_job_becomes_a_card_in_its_reserved_slot(db: Session, author: User) -> None:
    _run, task, job, asset = _run_with_job(db, author)
    _succeed(db, job, asset.id)
    db.flush()

    db.refresh(task)
    assert task.status == CanvasAgentTaskStatus.LANDED
    assert task.result_node_id

    node = db.get(CanvasNode, task.result_node_id)
    assert node is not None
    assert node.node_kind == CanvasNodeKind.IMAGE
    assert node.binding_asset_id == asset.id
    # Marked as the Agent's work, and dropped where the user was shown it would
    # appear at plan time.
    assert node.origin == CanvasNodeOrigin.AGENT
    assert (node.position_x, node.position_y) == (400, 120)
    # Born with a size. A card the browser made gets one from React Flow's
    # measurement on its next commit; one inserted server-side never passes
    # through that, and a picture card with no width renders at the image's
    # natural size — filling the whole viewport.
    assert (node.width, node.height) == (
        graph_service.DEFAULT_RESULT_WIDTH,
        graph_service.DEFAULT_RESULT_HEIGHT,
    )


def test_the_landed_card_is_wired_to_the_agent_that_made_it(db: Session, author: User) -> None:
    """Otherwise the result is an orphan and the canvas loses the one thing it
    is good at — showing where something came from."""
    run, task, job, asset = _run_with_job(db, author)
    _succeed(db, job, asset.id)
    db.flush()

    db.refresh(task)
    edges = graph_service.read_edges(db, run.canvas_id)
    assert any(
        edge.source_node_id == run.agent_node_id and edge.target_node_id == task.result_node_id
        for edge in edges
    )


def test_a_video_task_lands_as_a_video_card(db: Session, author: User) -> None:
    _run, task, job, asset = _run_with_job(db, author, operation=Operation.TEXT_TO_VIDEO.value)
    _succeed(db, job, asset.id)
    db.flush()

    db.refresh(task)
    node = db.get(CanvasNode, task.result_node_id)
    assert node is not None
    assert node.node_kind == CanvasNodeKind.VIDEO
    # The binding kind has to agree with the card kind: the thumbnail is
    # resolved off the binding and the badge off the node kind, so a video card
    # carrying an image binding is data that contradicts itself.
    assert (node.binding_json or {}).get("kind") == "video"


def test_landing_is_idempotent_under_a_redelivered_terminal(db: Session, author: User) -> None:
    """The conditional UPDATE on `result_node_id IS NULL` is the guard.

    A worker retry or a redelivered message must not leave the user with two
    identical cards for one generation they paid for once.
    """
    run, _task, job, asset = _run_with_job(db, author)
    _succeed(db, job, asset.id)
    db.flush()
    before = len(graph_service.read_nodes(db, run.canvas_id))

    # Replay the landing directly: the state machine itself would refuse a
    # second terminal transition, so this exercises the guard rather than it.
    db.refresh(job)
    agent_service.land_job_result(db, job=job)
    db.flush()

    assert len(graph_service.read_nodes(db, run.canvas_id)) == before


def test_a_failed_job_marks_the_task_rather_than_leaving_it_running(
    db: Session, author: User
) -> None:
    """The reason the hook sits on `transition` and not on `settle_success`:
    a task whose job failed would otherwise spin forever."""
    run, task, job, _asset = _run_with_job(db, author)
    sm.transition(db, job.id, JobStatus.QUEUED)
    sm.transition(db, job.id, JobStatus.SUBMITTED)
    sm.transition(
        db,
        job.id,
        JobStatus.FAILED,
        failure_code="PROVIDER_ERROR",
        failure_message="供应商返回错误",
    )
    db.flush()

    db.refresh(task)
    assert task.status == CanvasAgentTaskStatus.FAILED
    assert task.failure_code == "PROVIDER_ERROR"
    assert task.result_node_id is None
    # No card, and no phantom node left on the canvas.
    assert graph_service.read_nodes(db, run.canvas_id) == [
        node for node in graph_service.read_nodes(db, run.canvas_id) if node.id == "cnd_agent"
    ]


def test_the_run_settles_once_every_task_has(db: Session, author: User) -> None:
    run, _task, job, asset = _run_with_job(db, author)
    _succeed(db, job, asset.id)
    db.flush()

    db.refresh(run)
    assert run.status == CanvasAgentRunStatus.SUCCEEDED


def test_a_run_with_one_landed_and_one_failed_task_reports_partial(
    db: Session, author: User
) -> None:
    """Calling that a failure would tell the user their work is gone while it
    is sitting in front of them."""
    run, _first, job_a, asset = _run_with_job(db, author)
    second_job = jobs_service.submit(
        db,
        user_id=author.id,
        operation=Operation.TEXT_TO_IMAGE.value,
        quality_tier=QualityTier.STANDARD.value,
        params={"prompt": "第二张"},
        idempotency_key=new_id("idk"),
    ).job
    second = CanvasAgentTask(
        run_id=run.id,
        ordinal=1,
        operation=Operation.TEXT_TO_IMAGE.value,
        quality_tier=QualityTier.STANDARD.value,
        request_json={"prompt": "第二张"},
        generation_job_id=second_job.id,
        status=CanvasAgentTaskStatus.SUBMITTED.value,
        drop_x=400,
        drop_y=340,
    )
    db.add(second)
    db.flush()

    _succeed(db, job_a, asset.id)
    sm.transition(db, second_job.id, JobStatus.QUEUED)
    sm.transition(db, second_job.id, JobStatus.SUBMITTED)
    sm.transition(db, second_job.id, JobStatus.FAILED, failure_code="PROVIDER_ERROR")
    db.flush()

    db.refresh(run)
    assert run.status == CanvasAgentRunStatus.PARTIAL


def test_a_job_with_no_canvas_task_behind_it_is_untouched(db: Session, author: User) -> None:
    """The hook runs on every terminal transition in the system, so the
    overwhelming majority of jobs must pass through it as a no-op."""
    credits_service.grant(db, author.id, 100_000, idempotency_key=new_id("grant"))
    asset = _output_asset(db, author)
    job = jobs_service.submit(
        db,
        user_id=author.id,
        operation=Operation.TEXT_TO_IMAGE.value,
        quality_tier=QualityTier.STANDARD.value,
        params={"prompt": "普通任务"},
        idempotency_key=new_id("idk"),
    ).job

    _succeed(db, job, asset.id)
    db.flush()
    db.refresh(job)
    assert job.status == JobStatus.SUCCEEDED
    assert db.query(CanvasNode).count() == 0


def test_a_landing_failure_does_not_fail_the_job(
    db: Session, author: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Credits are already settled by the time this runs. Losing the card is
    recoverable; turning a paid-for, finished job into a failure is not."""
    _run, _task, job, asset = _run_with_job(db, author)

    def explode(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("landing blew up")

    monkeypatch.setattr(graph_service, "insert_agent_node", explode)
    _succeed(db, job, asset.id)
    db.flush()

    db.refresh(job)
    assert job.status == JobStatus.SUCCEEDED


@pytest.mark.parametrize(
    ("target", "event_type", "public_message"),
    [
        (JobStatus.SUCCEEDED, JobEventType.SUCCEEDED, "生成完成"),
        (JobStatus.CANCELLED, JobEventType.CANCELLED, "已取消"),
    ],
)
def test_a_missing_canvas_table_does_not_abort_a_terminal_transition(
    db: Session,
    author: User,
    monkeypatch: pytest.MonkeyPatch,
    target: JobStatus,
    event_type: JobEventType,
    public_message: str,
) -> None:
    """`UndefinedTable` aborts the Postgres transaction unless the hook
    isolates the SELECT behind a savepoint. Without that, `append_event`
    after `transition` raises `InFailedSqlTransaction` and the job never
    reaches a terminal status — the live poller / expire loop."""

    def explode(session: Session, **_kwargs: object) -> None:
        session.execute(text("SELECT 1 FROM canvas_agent_tasks_missing_on_purpose"))

    monkeypatch.setattr(agent_service, "land_job_result", explode)
    job = make_job(db, author, status=JobStatus.RUNNING)
    sm.transition(db, job.id, target)
    event = sm.append_event(
        db,
        job.id,
        event_type=event_type,
        status=target,
        public_message=public_message,
        progress=100,
    )
    db.flush()

    db.refresh(job)
    assert job.status == target
    assert job.finished_at is not None
    assert event.sequence == 1
    stored = db.query(JobEvent).filter(JobEvent.job_id == job.id).one()
    assert stored.event_type == event_type


# ---------------------------------------------------------------------------
# Putting a deleted card back
# ---------------------------------------------------------------------------


def test_restoring_puts_the_card_back_in_its_slot(db: Session, author: User) -> None:
    """Results land by themselves; this is only for after the user deleted the
    card and wants it back."""
    run, task, job, asset = _run_with_job(db, author)
    _succeed(db, job, asset.id)
    db.flush()
    db.refresh(task)
    landed_node_id = task.result_node_id

    graph_service.apply_ops(
        db,
        canvas_id=run.canvas_id,
        user_id=author.id,
        ops=[
            {
                "op_id": "op_del",
                "kind": "node.delete",
                "node_id": landed_node_id,
                "expected_revision": 1,
            }
        ],
    )
    db.flush()
    assert db.get(CanvasNode, landed_node_id) is None

    node = agent_service.restore_task_card(db, user_id=author.id, task_id=task.id)
    db.flush()
    assert node.id != landed_node_id
    assert node.binding_asset_id == asset.id
    assert (node.position_x, node.position_y) == (task.drop_x, task.drop_y)
    db.refresh(task)
    assert task.result_node_id == node.id


def test_restoring_is_refused_while_the_card_is_still_there(db: Session, author: User) -> None:
    """Otherwise a double-tap leaves two identical cards for one generation."""
    _run, task, job, asset = _run_with_job(db, author)
    _succeed(db, job, asset.id)
    db.flush()

    with pytest.raises(ValidationFailed):
        agent_service.restore_task_card(db, user_id=author.id, task_id=task.id)


def test_restoring_a_task_that_never_landed_is_refused(db: Session, author: User) -> None:
    _run, task, job, _asset = _run_with_job(db, author)
    sm.transition(db, job.id, JobStatus.QUEUED)
    sm.transition(db, job.id, JobStatus.SUBMITTED)
    sm.transition(db, job.id, JobStatus.FAILED, failure_code="PROVIDER_ERROR")
    db.flush()

    with pytest.raises(ValidationFailed):
        agent_service.restore_task_card(db, user_id=author.id, task_id=task.id)


def test_an_outsider_cannot_restore_someone_elses_card(
    db: Session, author: User, remixer: User
) -> None:
    run, task, job, asset = _run_with_job(db, author)
    _succeed(db, job, asset.id)
    db.flush()
    db.refresh(task)
    graph_service.apply_ops(
        db,
        canvas_id=run.canvas_id,
        user_id=author.id,
        ops=[
            {
                "op_id": "op_del",
                "kind": "node.delete",
                "node_id": task.result_node_id,
                "expected_revision": 1,
            }
        ],
    )
    db.flush()

    with pytest.raises(NotFound):
        agent_service.restore_task_card(db, user_id=remixer.id, task_id=task.id)
