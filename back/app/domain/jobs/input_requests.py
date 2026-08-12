"""Park a generation job on a follow-up question only its author can answer.

`WorkflowRunner` calls `suspend` when a `copy_generate` node decides the scene
description is worth a follow-up question (`app.workflows.nodes`). Unlike
`app.domain.jobs.async_tasks` (which a scheduler polls on a fixed cadence),
nothing here is claimed or ticked: the job simply waits at `AWAITING_INPUT`
until `POST /v1/generation-jobs/{id}/answer` calls `answer()`, or the beat
task `expire_stale_input_requests` (`app.workers.tasks`) decides nobody is
coming back and calls `expire()`.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.errors import ValidationFailed
from app.models import WorkflowInputRequest
from app.models.base import utcnow

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
    return session.scalar(
        select(WorkflowInputRequest).where(WorkflowInputRequest.job_id == job_id)
    )


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
