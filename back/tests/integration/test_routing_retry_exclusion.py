"""`route_score`'s retry behaviour: a provider that just failed for this job
must not be handed straight back to the LLM as if nothing happened.

Exercises `nodes.execute_route_score` directly rather than through the full
runner: this is a property of one node's state handling, not of the graph.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import GenerationJob, User
from app.models.base import new_id
from app.models.enums import Operation, QualityTier
from app.workflows.configs import RouteScoreConfig
from app.workflows.nodes import execute_route_score
from app.workflows.types import WorkflowContext


def _ctx(db: Session, user: User) -> WorkflowContext:
    job = GenerationJob(
        id=new_id("job"),
        user_id=user.id,
        operation=Operation.TEXT_TO_IMAGE.value,
        quality_tier=QualityTier.STANDARD.value,
        request_json={"prompt": "重试排除测试"},
        quoted_credits=0,
        reserved_credits=0,
        idempotency_key=new_id("idk"),
    )
    return WorkflowContext(session=db, job=job, prompt="重试排除测试", params={}, dry_run=True)


def test_a_provider_that_just_failed_is_excluded_from_the_retry(db: Session, author: User) -> None:
    ctx = _ctx(db, author)
    config = RouteScoreConfig(max_attempts=5)

    first = execute_route_score(ctx, config)
    assert first.port == "ok"
    first_provider = ctx.state["decision"].selected.provider

    # Simulate `execute_provider_generate` having just failed with this
    # provider and taken the `retry` port back to this node.
    ctx.state["failure_code"] = "PROVIDER_TEMPORARY_FAILURE"

    second = execute_route_score(ctx, config)
    assert second.port == "ok"
    second_decision = ctx.state["decision"]
    assert second_decision.selected.provider != first_provider

    excluded = next(
        c for c in second_decision.candidates if c.provider == first_provider
    )
    assert excluded.eligible is False
    assert excluded.filter_reason == "previously_failed_this_job"


def test_a_quality_rejection_does_not_exclude_the_provider(db: Session, author: User) -> None:
    """Unlike a provider failure, a quality-check retry is not evidence the
    provider itself is bad — it should stay eligible."""
    ctx = _ctx(db, author)
    config = RouteScoreConfig(max_attempts=5)

    first = execute_route_score(ctx, config)
    assert first.port == "ok"
    first_provider = ctx.state["decision"].selected.provider

    ctx.state["failure_code"] = "QUALITY_REJECTED"

    second = execute_route_score(ctx, config)
    assert second.port == "ok"
    second_decision = ctx.state["decision"]
    assert second_decision.selected.provider == first_provider
    assert ctx.state["tried_providers"] == set()
