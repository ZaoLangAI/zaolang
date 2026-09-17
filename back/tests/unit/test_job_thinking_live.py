"""Thinking frames are Redis-only: no JobEvent row, no sequence."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.domain.credits import service as credits_service
from app.domain.jobs import service as jobs_service
from app.models import JobEvent, User
from app.models.base import new_id
from app.models.enums import Operation, QualityTier
from app.workflows import nodes as workflow_nodes
from app.workflows.types import WorkflowContext


def test_publish_thinking_is_redis_only_and_has_no_sequence(
    db: Session, author: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    credits_service.grant(db, author.id, 5_000, idempotency_key=new_id("grant"))
    job = jobs_service.submit(
        db,
        user_id=author.id,
        operation=Operation.TEXT_TO_IMAGE,
        quality_tier=QualityTier.STANDARD,
        params={"prompt": "思考直播", "aspect_ratio": "16:9"},
        idempotency_key=new_id("idk"),
    ).job
    before = db.query(JobEvent).filter(JobEvent.job_id == job.id).count()
    published: list[dict[str, object]] = []
    monkeypatch.setattr(
        workflow_nodes.publisher,
        "publish_job_event",
        lambda job_id, payload: published.append(payload),
    )

    ctx = WorkflowContext(session=db, job=job, prompt="思考直播", params=dict(job.request_json))
    ctx.state["_current_node_id"] = "planning"
    ctx.state["_last_event_status"] = "queued"
    ctx.state["_last_event_progress"] = 12
    workflow_nodes.publish_thinking(ctx, "先构图")

    assert published == [
        {
            "event_type": "thinking",
            "node_id": "planning",
            "status": "queued",
            "progress": 12,
            "message": "",
            "thinking": "先构图",
        }
    ]
    assert "sequence" not in published[0]
    assert db.query(JobEvent).filter(JobEvent.job_id == job.id).count() == before


def test_publish_thinking_skips_empty_and_dry_run(
    db: Session, author: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    credits_service.grant(db, author.id, 5_000, idempotency_key=new_id("grant"))
    job = jobs_service.submit(
        db,
        user_id=author.id,
        operation=Operation.TEXT_TO_IMAGE,
        quality_tier=QualityTier.STANDARD,
        params={"prompt": "空思考", "aspect_ratio": "16:9"},
        idempotency_key=new_id("idk"),
    ).job
    published: list[object] = []
    monkeypatch.setattr(
        workflow_nodes.publisher,
        "publish_job_event",
        lambda *_a, **_k: published.append(1),
    )
    ctx = WorkflowContext(session=db, job=job, prompt="空思考", params={}, dry_run=True)
    workflow_nodes.publish_thinking(ctx, "不该发出")
    ctx.dry_run = False
    workflow_nodes.publish_thinking(ctx, "")
    assert published == []
