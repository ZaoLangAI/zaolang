"""Generation job submission and settlement.

Submission and settlement are deliberately separate: submission reserves credits
inside the request transaction, while settlement happens in the worker after the
provider has actually produced (or failed to produce) something.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.characters import service as characters_service
from app.domain.credits import service as credits_service
from app.domain.credits.pricing import Quote
from app.domain.credits.pricing import quote as compute_quote
from app.domain.errors import (
    Conflict,
    CreditsExceedBudget,
    InsufficientCredits,
    NotFound,
)
from app.domain.jobs import state_machine as sm
from app.domain.shortform import service as shortform_service
from app.domain.workflow_templates import service as workflow_templates_service
from app.models import GenerationJob, JobEvent
from app.models.enums import JobEventType, JobStatus
from app.platform_config import service as config_service
from app.platform_config.schemas import PricingConfig

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class SubmissionResult:
    job: GenerationJob
    quote: Quote
    replayed: bool = False


def quote_for(
    session: Session, *, operation: str, quality_tier: str, duration_seconds: int = 0
) -> Quote:
    """Prices a job using the live config, falling back to code defaults."""
    pricing = config_service.get_typed(session, "pricing", PricingConfig)
    return compute_quote(
        operation=operation,
        quality_tier=quality_tier,
        duration_seconds=duration_seconds,
        pricing=pricing.tier_pricing,
        per_second_surcharge=pricing.video_per_second_surcharge,
        base_seconds=pricing.video_base_seconds,
    )


def submit(
    session: Session,
    *,
    user_id: str,
    operation: str,
    quality_tier: str,
    params: dict[str, Any],
    idempotency_key: str,
    draft_id: str | None = None,
    source_work_version_id: str | None = None,
    max_credits: int | None = None,
) -> SubmissionResult:
    """Creates a job and reserves its credits.

    The unique `(user_id, idempotency_key)` index is what makes a double-tapped
    submit button produce one job rather than two reservations.
    """
    existing = session.scalar(
        select(GenerationJob).where(
            GenerationJob.user_id == user_id,
            GenerationJob.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        return SubmissionResult(
            job=existing,
            quote=Quote(
                credits=existing.quoted_credits,
                estimated_seconds=existing.estimated_seconds,
                breakdown={"base": existing.quoted_credits},
            ),
            replayed=True,
        )

    # Before quoting: a spec mismatch, or an unowned character, must not cost
    # the user a reservation.
    characters_service.apply_character_refs(session, user_id=user_id, params=params)
    shortform_service.assert_params_consistent(session, params)

    priced = quote_for(
        session,
        operation=operation,
        quality_tier=quality_tier,
        duration_seconds=int(params.get("duration_seconds") or 0),
    )
    if max_credits is not None and priced.credits > max_credits:
        raise CreditsExceedBudget(
            f"预计消耗 {priced.credits} 积分，超过你设置的 {max_credits} 上限。",
            quoted=priced.credits,
            max_credits=max_credits,
        )

    account = credits_service.get_or_create_account(session, user_id)
    if account.available_balance < priced.credits:
        raise InsufficientCredits(
            f"需要 {priced.credits} 积分，当前可用 {account.available_balance}。",
            required=priced.credits,
            available=account.available_balance,
        )

    # Pinned now, not resolved lazily at run time: a template published while
    # this job sits in the queue must not change what it runs. Left `None`
    # when nothing has ever been published for the operation yet (fresh
    # deploy before `make seed`) — `pipeline._resolve_graph` falls back to
    # the code-level default graph for those.
    active_template = workflow_templates_service.get_active(session, operation)

    job = GenerationJob(
        user_id=user_id,
        draft_id=draft_id,
        source_work_version_id=source_work_version_id,
        operation=operation,
        request_json=params,
        quality_tier=quality_tier,
        status=JobStatus.CREATED,
        quoted_credits=priced.credits,
        reserved_credits=priced.credits,
        max_credits=max_credits,
        idempotency_key=idempotency_key,
        estimated_seconds=priced.estimated_seconds,
        workflow_template_id=active_template.id if active_template else None,
    )
    session.add(job)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise Conflict("相同请求正在处理中。") from exc

    credits_service.reserve(session, user_id, priced.credits, job_id=job.id)
    sm.append_event(
        session,
        job.id,
        event_type=JobEventType.QUEUED,
        status=JobStatus.CREATED,
        public_message="任务已创建，正在排队。",
        progress=2,
    )
    return SubmissionResult(job=job, quote=priced)


def settle_success(session: Session, job: GenerationJob, *, actual_credits: int) -> None:
    """Captures the reservation and returns any unused portion."""
    credits_service.capture(session, job.user_id, job_id=job.id, actual_amount=actual_credits)


def settle_release(session: Session, job: GenerationJob, *, reason: str) -> None:
    """Returns the reservation in full.

    Safe to call more than once: an already-settled job is left untouched
    rather than raising, because the retry paths that call this cannot always
    know whether an earlier attempt got that far.
    """
    try:
        credits_service.release(session, job.user_id, job_id=job.id, reason=reason)
    except Conflict:
        logger.info("job %s reservation already settled", job.id)


def get_owned_job(session: Session, job_id: str, user_id: str) -> GenerationJob:
    job = session.get(GenerationJob, job_id)
    if job is None or job.user_id != user_id:
        # Not "forbidden": revealing that another user's job exists is a leak.
        raise NotFound("任务不存在。")
    return job


def progress_for(session: Session, job: GenerationJob) -> int:
    """Progress as reported by the most recent event.

    Terminal jobs always read 100 so a client that missed the final event
    still renders a finished bar.
    """
    if JobStatus(job.status).is_terminal:
        return 100
    latest = session.scalar(
        select(JobEvent.progress)
        .where(JobEvent.job_id == job.id)
        .order_by(JobEvent.sequence.desc())
        .limit(1)
    )
    return int(latest or 0)
