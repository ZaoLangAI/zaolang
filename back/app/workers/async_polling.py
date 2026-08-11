"""One tick of the external-render poller.

A plain function rather than task code so tests drive it directly, matching
`workers/pipeline.py`. Three outcomes per claimed row, and the whole point is
that all three end with the job either progressing or settled — never left
`RUNNING` with nobody responsible for it:

* still rendering — write a heartbeat event so the user's stream and the ops
  console keep moving, then book the next check;
* finished — record the attempt, hand the result to the suspended workflow
  and let it run on to quality check and settlement;
* failed or timed out — resume down the node's failure port, which is the
  same retry/fail wiring a synchronous provider failure takes.

Cancellation is checked first on every tick. The synchronous path only checks
before calling `submit()`, which leaves the whole render window — minutes —
during which a user can press cancel and nothing would notice.
"""

from __future__ import annotations

import logging
from dataclasses import fields
from typing import Any

from sqlalchemy.orm import Session

from app.agents import router
from app.domain.jobs import async_tasks
from app.domain.jobs import service as jobs_service
from app.domain.jobs import state_machine as sm
from app.models import AsyncProviderTask, GenerationJob, ProviderAttempt
from app.models.base import utcnow
from app.models.enums import JobEventType, JobStatus, ProviderAttemptStatus
from app.providers.base import GenerationRequest, GenerationResult
from app.realtime import publisher
from app.workers.pipeline import resolve_graph
from app.workflows.runner import WorkflowRunner
from app.workflows.types import WorkflowContext

logger = logging.getLogger(__name__)

# Progress shown while a render is in flight. Deliberately between
# `provider_generate`'s 45 and `quality_check`'s 78, and deliberately
# monotonic: the bar creeps toward the ceiling with each check instead of
# claiming to know how far along the upstream really is.
_PROGRESS_FLOOR = 46
_PROGRESS_CEILING = 70


def poll_once(session: Session, *, limit: int = 50) -> int:
    handled = 0
    for task in async_tasks.claim_due(session, limit=limit):
        try:
            _advance(session, task)
            handled += 1
        except Exception:
            # One stuck provider must not stop the others. The claim lease
            # expiring is what brings this row back.
            logger.exception("failed to advance async provider task %s", task.id)
            session.rollback()
    return handled


def _advance(session: Session, task: AsyncProviderTask) -> None:
    job = session.get(GenerationJob, task.job_id)
    if job is None or JobStatus(job.status).is_terminal:
        # The job was settled by something else (expiry sweep, an admin
        # action). Nothing left to resume.
        async_tasks.settle(session, task)
        session.commit()
        return

    capability = router.build_catalog(session).get(task.capability_name)
    if capability is None:
        # The endpoint was deleted or disabled mid-render. There is no way to
        # ask about the task any more, so fail the job rather than leave it
        # waiting on something unreachable.
        logger.warning(
            "async task %s references capability %s which is no longer in the catalogue",
            task.id,
            task.capability_name,
        )
        _close_attempt(session, task, ProviderAttemptStatus.FAILED, None)
        _resume_failed(session, job, task, code="PROVIDER_TEMPORARY_FAILURE")
        return

    provider = capability.provider_factory()

    if job.cancel_requested_at is not None:
        _cancel(session, job, task, provider)
        return

    request = _request_from(task.request_json)
    result = provider.poll(task.external_task_id, request)

    if result.pending and utcnow() < task.deadline_at:
        _heartbeat(session, job, task)
        async_tasks.reschedule(session, task)
        session.commit()
        return

    if result.pending:
        logger.warning("async task %s exceeded its deadline; giving up", task.id)
        provider.cancel(task.external_task_id)
        _close_attempt(session, task, ProviderAttemptStatus.TIMED_OUT, result)
        _resume_failed(session, job, task, code="PROVIDER_TIMEOUT")
        return

    router.record_attempt_outcome(
        session,
        provider=task.capability_name,
        operation=job.operation,
        quality_tier=job.quality_tier,
        succeeded=result.succeeded,
        latency_ms=result.latency_ms,
        cost_minor=result.cost_minor,
    )

    if not result.succeeded or result.object_key is None:
        _close_attempt(session, task, ProviderAttemptStatus.FAILED, result)
        _resume_failed(session, job, task, code=result.failure_code or "PROVIDER_TEMPORARY_FAILURE")
        return

    _close_attempt(session, task, ProviderAttemptStatus.SUCCEEDED, result)
    _resume_succeeded(session, job, task, capability=capability, result=result)


def _cancel(session: Session, job: GenerationJob, task: AsyncProviderTask, provider: Any) -> None:
    """Honours a cancel that arrived while the render was in flight.

    Same settlement as `execute_provider_generate`'s cancellation branch —
    release the reservation, move to `CANCELLED`, tell the user. Telling the
    upstream to stop is best effort: it may bill us anyway, and settlement
    follows what we actually reserved, not what they charge.
    """
    provider.cancel(task.external_task_id)
    _close_attempt(session, task, ProviderAttemptStatus.CANCELLED, None)
    jobs_service.settle_release(session, job, reason="cancelled_by_user")
    sm.transition(session, job.id, JobStatus.CANCELLED)
    async_tasks.settle(session, task)
    _emit(
        session,
        job,
        JobEventType.CANCELLED,
        JobStatus.CANCELLED,
        "任务已取消，积分已退回",
        100,
    )
    session.commit()


def _heartbeat(session: Session, job: GenerationJob, task: AsyncProviderTask) -> None:
    """The reason this whole mechanism exists from a user's point of view.

    Without it a video job would show one frozen status for minutes and then
    jump straight to done — indistinguishable, while you are waiting, from a
    job that died.
    """
    progress = min(_PROGRESS_CEILING, _PROGRESS_FLOOR + task.poll_count)
    _emit(
        session,
        job,
        JobEventType.PROGRESS,
        JobStatus.RUNNING,
        "正在渲染，请稍候",
        progress,
        payload={"external_task_id": task.external_task_id, "poll_count": task.poll_count},
    )


def _resume_succeeded(
    session: Session,
    job: GenerationJob,
    task: AsyncProviderTask,
    *,
    capability: Any,
    result: GenerationResult,
) -> None:
    ctx = _context(session, job, task)
    ctx.state["result"] = result
    ctx.state["capability"] = capability
    node_id = task.node_id
    async_tasks.settle(session, task)
    session.commit()
    _runner(session, job).resume(ctx, node_id=node_id, port="succeeded")
    session.commit()


def _resume_failed(
    session: Session, job: GenerationJob, task: AsyncProviderTask, *, code: str
) -> None:
    """Continues down the same port a synchronous failure would have taken.

    `retry` rather than `failed`, because that is what `provider_generate`
    returns unless its graph explicitly opted out — routing back through
    `route_score` is how another provider gets a turn, and the attempt budget
    restored from the checkpoint is what stops it looping.
    """
    ctx = _context(session, job, task)
    ctx.state["failure_code"] = code
    node_id = task.node_id
    async_tasks.settle(session, task)
    _emit(
        session,
        job,
        JobEventType.PROGRESS,
        JobStatus.RUNNING,
        "这条线路暂时不可用，正在尝试其他路线",
        45,
        internal_code=code,
    )
    session.commit()
    runner = _runner(session, job)
    port = "retry" if _retries_on_failure(runner, node_id) else "failed"
    runner.resume(ctx, node_id=node_id, port=port)
    session.commit()


def _retries_on_failure(runner: WorkflowRunner, node_id: str) -> bool:
    node = runner.node(node_id)
    return bool((node.config or {}).get("retry_on_failure", True)) if node is not None else True


def _runner(session: Session, job: GenerationJob) -> WorkflowRunner:
    """The same graph the suspended run was walking.

    `resolve_graph` prefers the template pinned on the job, so a resume can
    never land in a different graph than the one that suspended — even if an
    admin published a new version while the render was in flight.
    """
    return WorkflowRunner(resolve_graph(session, job))


def _context(session: Session, job: GenerationJob, task: AsyncProviderTask) -> WorkflowContext:
    """Rebuilds the workflow state the suspended run had.

    Only the JSON-safe slice is restored (`_provider_checkpoint`); the live
    routing objects are re-derived from the catalogue by the caller.
    """
    params = dict(job.request_json)
    ctx = WorkflowContext(
        session=session, job=job, prompt=str(params.get("prompt", "")), params=params
    )
    checkpoint = dict(task.state_checkpoint_json or {})
    ctx.state["attempt_number"] = int(checkpoint.get("attempt_number") or 1)
    ctx.state["route_attempts"] = int(checkpoint.get("route_attempts") or 1)
    ctx.state["tried_providers"] = set(checkpoint.get("tried_providers") or ())
    ctx.state["intent_hint"] = dict(checkpoint.get("intent_hint") or {})
    return ctx


def _request_from(payload: dict[str, Any]) -> GenerationRequest:
    known = {field.name for field in fields(GenerationRequest)}
    return GenerationRequest(**{k: v for k, v in payload.items() if k in known})


def _close_attempt(
    session: Session,
    task: AsyncProviderTask,
    status: ProviderAttemptStatus,
    result: GenerationResult | None,
) -> None:
    """Settles the `ProviderAttempt` opened when the render was submitted."""
    if not task.provider_attempt_id:
        return
    attempt = session.get(ProviderAttempt, task.provider_attempt_id)
    if attempt is None:
        return
    attempt.status = status
    if result is not None:
        attempt.latency_ms = result.latency_ms
        attempt.cost_minor = result.cost_minor
        attempt.failure_code = result.failure_code
    session.flush()


def _emit(
    session: Session,
    job: GenerationJob,
    event_type: JobEventType,
    status: JobStatus,
    message: str,
    progress: int,
    *,
    internal_code: str | None = None,
    payload: dict[str, object] | None = None,
) -> None:
    """Mirrors `workflows.nodes._emit` for events raised outside a node.

    Kept separate rather than shared because that one takes a
    `WorkflowContext` and commits on the caller's behalf; here the tick owns
    the transaction boundary.
    """
    event = sm.append_event(
        session,
        job.id,
        event_type=event_type,
        status=status,
        public_message=message,
        progress=progress,
        internal_code=internal_code,
        payload=payload,
    )
    session.flush()
    publisher.publish_job_event(
        job.id,
        {
            "sequence": event.sequence,
            "event_type": event.event_type,
            "status": event.status,
            "progress": event.progress,
            "message": event.public_message,
        },
    )
