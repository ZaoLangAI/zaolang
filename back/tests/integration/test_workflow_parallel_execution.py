"""Fan-out/join: `barrier` (all branches must succeed) vs `race` (any one).

Uses a hand-built graph (not a seeded template) with two parallel
`route_score` branches whose outcome is made deterministic per-branch via
`max_latency_ms` — one branch has no latency budget (always finds a fake
provider), the other's budget (1000ms) is below both fakes' typical latency
so it always comes back `no_candidate`. This isolates the join's aggregation
semantics from anything provider/LLM-flaky.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.domain.credits import service as credits_service
from app.domain.jobs import service as jobs_service
from app.models import User
from app.models.base import new_id
from app.models.enums import JobStatus, Operation, QualityTier
from app.workflows.graph import WorkflowGraph
from app.workflows.runner import WorkflowRunner
from app.workflows.types import WorkflowContext


@pytest.fixture
def funded(db: Session, author: User) -> User:
    credits_service.grant(db, author.id, 5_000, idempotency_key=new_id("grant"))
    db.flush()
    return author


def _submit(db: Session, user: User):  # type: ignore[no-untyped-def]
    result = jobs_service.submit(
        db,
        user_id=user.id,
        operation=Operation.TEXT_TO_IMAGE,
        quality_tier=QualityTier.STANDARD,
        params={"prompt": "并行分支测试", "aspect_ratio": "16:9"},
        idempotency_key=new_id("idk"),
    )
    return result.job


def _fanout_graph(*, join_mode: str, losing_branch_id: str | None) -> dict:
    """Two `route_score` branches converging on one `join`.

    `losing_branch_id`, if given, gets a `max_latency_ms` below every fake
    provider's typical latency so it deterministically takes the
    `no_candidate` port; the other branch runs unfiltered and always
    succeeds. `None` means both branches succeed.
    """

    def route_config(node_id: str) -> dict:
        if node_id == losing_branch_id:
            return {"max_attempts": 5, "max_latency_ms": 1_000}
        return {"max_attempts": 5}

    nodes = [
        {"id": "safety", "type": "safety_check", "config": {}},
        {"id": "route_a", "type": "route_score", "config": route_config("route_a")},
        {"id": "route_b", "type": "route_score", "config": route_config("route_b")},
        {"id": "join", "type": "join", "config": {"mode": join_mode, "success_ports": ["ok"]}},
        {
            "id": "provider_generate",
            "type": "provider_generate",
            "config": {"retry_on_failure": False},
        },
        {"id": "quality_check", "type": "quality_check", "config": {}},
        {"id": "settle_success", "type": "settle_success", "config": {}},
        {"id": "fail", "type": "fail", "config": {}},
    ]
    edges = [
        {"from": "safety", "from_port": "pass", "to": "route_a", "kind": "parallel"},
        {"from": "safety", "from_port": "pass", "to": "route_b", "kind": "parallel"},
        {"from": "safety", "from_port": "reject", "to": "fail"},
        {"from": "route_a", "from_port": "ok", "to": "join"},
        {"from": "route_a", "from_port": "no_candidate", "to": "join"},
        {"from": "route_a", "from_port": "retries_exhausted", "to": "join"},
        {"from": "route_b", "from_port": "ok", "to": "join"},
        {"from": "route_b", "from_port": "no_candidate", "to": "join"},
        {"from": "route_b", "from_port": "retries_exhausted", "to": "join"},
        {"from": "join", "from_port": "ok", "to": "provider_generate"},
        {"from": "join", "from_port": "partial_failure", "to": "fail"},
        {"from": "provider_generate", "from_port": "succeeded", "to": "quality_check"},
        {"from": "provider_generate", "from_port": "failed", "to": "fail"},
        {"from": "quality_check", "from_port": "pass", "to": "settle_success"},
        {"from": "quality_check", "from_port": "fail", "to": "fail"},
        {"from": "quality_check", "from_port": "retry", "to": "fail"},
    ]
    return {"nodes": nodes, "edges": edges}


def _run(db: Session, job, *, join_mode: str, losing_branch_id: str | None):  # type: ignore[no-untyped-def]
    graph = WorkflowGraph.from_dict(
        _fanout_graph(join_mode=join_mode, losing_branch_id=losing_branch_id)
    )
    ctx = WorkflowContext(
        session=db, job=job, prompt=job.request_json["prompt"], params=dict(job.request_json)
    )
    return WorkflowRunner(graph).run(ctx)


def test_barrier_join_succeeds_when_every_branch_succeeds(db: Session, funded: User) -> None:
    job = _submit(db, funded)
    outcome = _run(db, job, join_mode="barrier", losing_branch_id=None)
    assert outcome.status == JobStatus.SUCCEEDED


def test_barrier_join_fails_the_job_when_one_branch_loses(db: Session, funded: User) -> None:
    job = _submit(db, funded)
    outcome = _run(db, job, join_mode="barrier", losing_branch_id="route_b")
    assert outcome.status == JobStatus.FAILED


def test_race_join_succeeds_as_long_as_one_branch_wins(db: Session, funded: User) -> None:
    job = _submit(db, funded)
    outcome = _run(db, job, join_mode="race", losing_branch_id="route_b")
    assert outcome.status == JobStatus.SUCCEEDED


def test_race_join_still_fails_when_every_branch_loses(db: Session, funded: User) -> None:
    job = _submit(db, funded)
    graph_dict = _fanout_graph(join_mode="race", losing_branch_id="route_b")
    # Force both branches to lose by also starving route_a's latency budget.
    graph_dict["nodes"][1]["config"] = {"max_attempts": 5, "max_latency_ms": 1_000}
    graph = WorkflowGraph.from_dict(graph_dict)
    ctx = WorkflowContext(
        session=db, job=job, prompt=job.request_json["prompt"], params=dict(job.request_json)
    )
    outcome = WorkflowRunner(graph).run(ctx)
    assert outcome.status == JobStatus.FAILED
