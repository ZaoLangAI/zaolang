"""Park a generation job on a follow-up question only its author can answer.

`WorkflowRunner` calls `suspend` when a `copy_generate` node decides the scene
description is worth a follow-up question (`app.workflows.nodes`). Unlike
`app.domain.jobs.async_tasks` (which a scheduler polls on a fixed cadence),
nothing here is claimed or ticked: the job simply waits at `AWAITING_INPUT`
until `POST /v1/generation-jobs/{id}/answer` (or the admin equivalent
`POST /v1/admin/jobs/{id}/answer`) calls `answer()`, or the beat
task `expire_stale_input_requests` (`app.workers.tasks`) decides nobody is
coming back and calls `expire()`.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.errors import NotFound, ValidationFailed
from app.domain.jobs import service as jobs_service
from app.domain.jobs import state_machine as sm
from app.models import GenerationJob, JobEvent, WorkflowInputRequest
from app.models.base import utcnow
from app.models.enums import JobEventType, JobStatus
from app.realtime import publisher
from app.workflows.types import WorkflowContext

# An author is not a provider SLA: this is generous compared to
# `async_tasks.TASK_TIMEOUT_SECONDS` (8 minutes) on purpose — abandoning a
# question after a short nap should not cost the reservation.
INPUT_TIMEOUT_SECONDS = 6 * 3600


def suspend(
    session: Session,
    *,
    job_id: str,
    node_id: str,
    checkpoint: dict[str, Any],
    now: dt.datetime | None = None,
) -> WorkflowInputRequest:
    """Writes the row that proves an `AWAITING_INPUT` job is still owned by someone.

    `checkpoint` is the JSON-safe dict produced by
    `app.workflows.nodes._input_checkpoint`: the output key plus the
    questions and state slice the resumed walk needs.
    """
    moment = now or utcnow()
    existing = find_for_job(session, job_id)
    if existing is not None:
        # A job asks one question at a time; replacing keeps the unique
        # constraint honest if a node re-suspends before the previous row was
        # cleaned up (should not happen, but matches `async_tasks.suspend`'s
        # own defensiveness).
        session.delete(existing)
        session.flush()

    row = WorkflowInputRequest(
        job_id=job_id,
        node_id=node_id,
        output_key=str(checkpoint.get("output_key") or ""),
        questions_json=list(checkpoint.get("questions") or []),
        state_checkpoint_json=dict(checkpoint.get("state") or {}),
        expires_at=moment + dt.timedelta(seconds=INPUT_TIMEOUT_SECONDS),
    )
    session.add(row)
    session.flush()
    return row


def find_for_job(session: Session, job_id: str) -> WorkflowInputRequest | None:
    return session.scalar(select(WorkflowInputRequest).where(WorkflowInputRequest.job_id == job_id))


def due_for_expiry(
    session: Session, *, limit: int = 100, now: dt.datetime | None = None
) -> list[WorkflowInputRequest]:
    moment = now or utcnow()
    return list(
        session.scalars(
            select(WorkflowInputRequest)
            .where(WorkflowInputRequest.expires_at <= moment)
            .limit(limit)
        )
    )


def due_for_user_cancel(session: Session, *, limit: int = 100) -> list[WorkflowInputRequest]:
    """Parked questions whose author already asked to stop — ignore `expires_at`."""
    return list(
        session.scalars(
            select(WorkflowInputRequest)
            .join(GenerationJob, GenerationJob.id == WorkflowInputRequest.job_id)
            .where(
                GenerationJob.cancel_requested_at.is_not(None),
                GenerationJob.status == JobStatus.AWAITING_INPUT.value,
            )
            .limit(limit)
        )
    )


def validate_answers(
    questions: list[dict[str, Any]], raw_answers: dict[str, str | list[str]]
) -> dict[str, str | list[str]]:
    """Checks every required question was answered legally, and sanitizes the rest.

    An answer for a question id outside `questions` is silently dropped
    rather than rejected — the same tolerance
    `copywriter._sanitize_clarify_question` already extends the other
    direction, to a model's own output.
    """
    sanitized: dict[str, str | list[str]] = {}
    for question in questions:
        question_id = str(question.get("id") or "")
        kind = question.get("kind")
        prompt = str(question.get("prompt") or question_id)
        required = bool(question.get("required"))
        options = {str(option.get("value")) for option in question.get("options") or []}
        raw = raw_answers.get(question_id)

        if kind == "multi_choice":
            values = [str(v) for v in raw if str(v) in options] if isinstance(raw, list) else []
            if required and not values:
                raise ValidationFailed(f"问题「{prompt}」必须回答。")
            if values:
                sanitized[question_id] = values
            continue

        text = raw.strip() if isinstance(raw, str) else ""
        if kind == "single_choice" and text and text not in options:
            raise ValidationFailed(f"问题「{prompt}」的选项不合法。")
        if required and not text:
            raise ValidationFailed(f"问题「{prompt}」必须回答。")
        if text:
            sanitized[question_id] = text[:600]
    return sanitized


def settle(session: Session, request: WorkflowInputRequest) -> None:
    """Drops the row once its questions have been answered (or abandoned).

    Deleting rather than flagging, same reasoning as `async_tasks.settle`:
    the row exists to say "someone still has to come back for this job", and
    a settled one has no readers.
    """
    session.delete(request)
    session.flush()


@dataclass(slots=True)
class _AcceptedAnswers:
    job: GenerationJob
    ctx: WorkflowContext
    node_id: str
    event: JobEvent


def resume_context(
    session: Session, job: GenerationJob, request: WorkflowInputRequest
) -> WorkflowContext:
    """Rebuilds the workflow state a planning/`copy_generate` suspension had.

    Only the JSON-safe slice written by `_input_checkpoint` is restored; a
    live routing decision, if any ran before this node, was never part of it
    and stays whatever `route_score` would recompute on its own next visit.
    """
    params = dict(job.request_json)
    ctx = WorkflowContext(
        session=session, job=job, prompt=str(params.get("prompt", "")), params=params
    )
    checkpoint = dict(request.state_checkpoint_json or {})
    ctx.state[request.output_key] = dict(checkpoint.get("output_value") or {})
    ctx.state["attempt_number"] = int(checkpoint.get("attempt_number") or 1)
    # 0, not 1: a planning/`copy_generate` checkpoint written before
    # `route_score` has `route_attempts=0`. `or 1` would treat that 0 as
    # missing and the next `route_score` increment would skip attempt 1.
    ctx.state["route_attempts"] = int(checkpoint.get("route_attempts") or 0)
    # Older checkpoints had no `attempt_seq`: their job-wide
    # `route_attempts` was the sequence number.
    ctx.state["attempt_seq"] = int(
        checkpoint.get("attempt_seq") or checkpoint.get("route_attempts") or 0
    )
    ctx.state["tried_providers"] = set(checkpoint.get("tried_providers") or ())
    ctx.state["intent_hint"] = dict(checkpoint.get("intent_hint") or {})
    return ctx


def _accept(
    session: Session, job: GenerationJob, raw_answers: dict[str, str | list[str]]
) -> _AcceptedAnswers:
    if JobStatus(job.status) != JobStatus.AWAITING_INPUT:
        raise ValidationFailed("当前任务不在等待回答的状态。")
    request = find_for_job(session, job.id)
    if request is None:
        raise NotFound("没有待回答的问题。")

    answers = validate_answers(request.questions_json, raw_answers)
    ctx = resume_context(session, job, request)
    output = dict(ctx.state.get(request.output_key) or {})
    output["clarify_answers"] = answers
    ctx.state[request.output_key] = output
    node_id = request.node_id

    settle(session, request)
    job = sm.transition(session, job.id, JobStatus.RUNNING)
    ctx.job = job
    event = sm.append_event(
        session,
        job.id,
        event_type=JobEventType.PROGRESS,
        status=JobStatus.RUNNING,
        public_message="已收到你的回答，正在继续生成",
        progress=jobs_service.progress_for(session, job),
        node_id=node_id,
    )
    return _AcceptedAnswers(job=job, ctx=ctx, node_id=node_id, event=event)


def answer(
    session: Session, job: GenerationJob, raw_answers: dict[str, str | list[str]]
) -> GenerationJob:
    """Folds the author's answers in and resumes the graph from the parked node.

    Shared by the C-end `/generation-jobs/{id}/answer` and the admin
    `/admin/jobs/{id}/answer` (sandbox try-it uses the latter because
    `get_owned_job` hides `origin=sandbox` from the C-end). Resume runs
    inline, same as the C-end path: nothing else will come back and finish
    this the way a provider poll would.
    """
    from app.domain.jobs.cancellation import honor_user_cancel
    from app.workers.pipeline import resume_after_input

    session.refresh(job)
    if job.cancel_requested_at is not None:
        job = honor_user_cancel(session, job)
        session.commit()
        return job

    accepted = _accept(session, job, raw_answers)
    session.commit()
    publisher.publish_job_event(
        accepted.job.id,
        {
            "sequence": accepted.event.sequence,
            "event_type": accepted.event.event_type,
            "status": accepted.event.status,
            "progress": accepted.event.progress,
            "message": accepted.event.public_message,
            "node_id": accepted.event.node_id,
        },
    )
    resume_after_input(accepted.job, accepted.ctx, node_id=accepted.node_id)
    session.commit()
    session.refresh(accepted.job)
    return accepted.job
