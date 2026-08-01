"""The generation pipeline.

Runs as a plain function so it can be executed inline by tests and integration
runs without a broker, while the Celery task is a thin wrapper around it.

Order is fixed and every stage writes a `JobEvent`:

    safety → plan → route → provider attempt → quality → settle

A safety rejection short-circuits everything and releases the reservation. A
quality failure may retry once through routing. Whatever happens, the
reservation ends in exactly one capture or one release.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.agents import planner, quality, router, safety
from app.domain.credits.pricing import settlement_credits
from app.domain.jobs import service as jobs_service
from app.domain.jobs import state_machine as sm
from app.domain.media import service as media_service
from app.models import Draft, GenerationJob, ProviderAttempt
from app.models.base import utcnow
from app.models.enums import (
    JobEventType,
    JobStatus,
    ModerationStage,
    ModerationStatus,
    ProviderAttemptStatus,
)
from app.observability.context import set_job_id
from app.providers.base import GenerationRequest
from app.providers.fake import get_provider
from app.realtime import publisher

logger = logging.getLogger(__name__)

MAX_PROVIDER_ATTEMPTS = 2


@dataclass(slots=True)
class PipelineOutcome:
    status: JobStatus
    failure_code: str | None = None
    asset_id: str | None = None


def run_generation_pipeline(session: Session, job_id: str) -> PipelineOutcome:
    job = session.get(GenerationJob, job_id)
    if job is None:
        raise LookupError(f"job {job_id} not found")
    set_job_id(job.id)

    if JobStatus(job.status).is_terminal:
        logger.info("job %s already terminal (%s)", job.id, job.status)
        return PipelineOutcome(status=JobStatus(job.status))

    try:
        return _execute(session, job)
    except Exception as exc:
        logger.exception("pipeline crashed for job %s", job.id)
        _fail(session, job, code="INTERNAL_ERROR", message="生成过程出现异常，积分已退回。")
        raise exc from None


def _execute(session: Session, job: GenerationJob) -> PipelineOutcome:
    params = dict(job.request_json)
    prompt = str(params.get("prompt", ""))

    job = sm.transition(session, job.id, JobStatus.QUEUED)
    _emit(session, job, JobEventType.SAFETY, JobStatus.QUEUED, "正在进行安全检查", 8)

    verdict = safety.review(
        session,
        text=prompt,
        stage=ModerationStage.PRE_GENERATION,
        subject_type="generation_job",
        subject_id=job.id,
        job_id=job.id,
        user_id=job.user_id,
    )
    if verdict.status == ModerationStatus.REJECTED:
        # Hard veto: nothing downstream may override this.
        _fail(
            session,
            job,
            code="MODERATION_REJECTED",
            message=verdict.public_message or "内容未通过安全检查。",
            event_type=JobEventType.FAILED,
        )
        return PipelineOutcome(status=JobStatus.FAILED, failure_code="MODERATION_REJECTED")

    _emit(session, job, JobEventType.PLANNING, JobStatus.QUEUED, "正在规划生成方案", 16)
    planner.plan(
        session,
        intent=prompt,
        source_params=params,
        requested_operation=job.operation,
        job_id=job.id,
        user_id=job.user_id,
    )

    attempt_number = 0
    last_failure: str | None = None

    while attempt_number < MAX_PROVIDER_ATTEMPTS:
        attempt_number += 1

        _emit(session, job, JobEventType.ROUTING, JobStatus.QUEUED, "正在选择生成路线", 24)
        decision = router.route(session, operation=job.operation, quality_tier=job.quality_tier)
        job.routing_trace_json = decision.trace()
        session.flush()

        if decision.selected is None or decision.capability is None:
            _fail(
                session,
                job,
                code="PROVIDER_TEMPORARY_FAILURE",
                message="暂时没有可用的生成路线，积分已退回。",
            )
            return PipelineOutcome(
                status=JobStatus.FAILED, failure_code="PROVIDER_TEMPORARY_FAILURE"
            )

        capability = decision.capability
        job.selected_route_summary_json = {
            "provider": capability.name,
            "provider_kind": capability.kind.value,
            "model_or_workflow": capability.model_or_workflow,
            "score": decision.selected.total_score,
            "reason": decision.reason,
        }
        session.flush()

        # A retry re-enters the loop with the job already running, and the state
        # machine rightly refuses running→running.
        if job.status == JobStatus.QUEUED:
            job = sm.transition(session, job.id, JobStatus.SUBMITTED)
        _emit(session, job, JobEventType.GENERATING, JobStatus.SUBMITTED, "正在生成", 40)
        if job.status != JobStatus.RUNNING:
            job = sm.transition(session, job.id, JobStatus.RUNNING)

        if _cancelled(session, job):
            return _cancel(session, job)

        result = get_provider(capability.name).submit(
            GenerationRequest(
                job_id=job.id,
                operation=job.operation,
                quality_tier=job.quality_tier,
                prompt=prompt,
                negative_prompt=params.get("negative_prompt"),
                seed=params.get("seed"),
                aspect_ratio=str(params.get("aspect_ratio") or "16:9"),
                duration_seconds=int(params.get("duration_seconds") or 0),
            )
        )

        session.add(
            ProviderAttempt(
                job_id=job.id,
                provider=capability.name,
                provider_kind=capability.kind,
                model_or_workflow_version=capability.model_or_workflow,
                external_task_id=result.external_task_id,
                attempt_number=attempt_number,
                status=(
                    ProviderAttemptStatus.SUCCEEDED
                    if result.succeeded
                    else ProviderAttemptStatus.FAILED
                ),
                cost_minor=result.cost_minor,
                latency_ms=result.latency_ms,
                failure_code=result.failure_code,
                raw_metadata_redacted_json=result.metadata,
                created_at=utcnow(),
            )
        )
        router.record_attempt_outcome(
            session,
            provider=capability.name,
            operation=job.operation,
            quality_tier=job.quality_tier,
            succeeded=result.succeeded,
            latency_ms=result.latency_ms,
            cost_minor=result.cost_minor,
        )
        session.flush()

        if not result.succeeded or result.object_key is None:
            last_failure = result.failure_code or "PROVIDER_TEMPORARY_FAILURE"
            _emit(
                session,
                job,
                JobEventType.PROGRESS,
                JobStatus.RUNNING,
                "这条线路暂时不可用，正在尝试其他路线",
                45,
                internal_code=last_failure,
            )
            continue

        _emit(session, job, JobEventType.QUALITY_CHECK, JobStatus.RUNNING, "正在校验输出质量", 78)
        assessment = quality.evaluate(
            session,
            prompt=prompt,
            output_summary={
                "width": result.width,
                "height": result.height,
                "duration_ms": result.duration_ms,
                "provider": capability.name,
            },
            attempt_number=attempt_number,
            job_id=job.id,
            user_id=job.user_id,
        )
        if assessment.data.get("verdict") == "fail" and assessment.data.get("should_retry"):
            last_failure = "QUALITY_REJECTED"
            _emit(
                session,
                job,
                JobEventType.PROGRESS,
                JobStatus.RUNNING,
                "输出质量不理想，正在重新生成",
                50,
                internal_code=last_failure,
            )
            continue

        asset = media_service.register_generated_asset(
            session,
            owner_user_id=job.user_id,
            object_key=result.object_key,
            mime_type=result.mime_type,
            width=result.width,
            height=result.height,
            duration_ms=result.duration_ms,
            generation_job_id=job.id,
            provenance={
                "provider": capability.name,
                "model_or_workflow": capability.model_or_workflow,
                "operation": job.operation,
                "quality_tier": job.quality_tier,
            },
        )
        if job.draft_id:
            draft = session.get(Draft, job.draft_id)
            if draft is not None:
                draft.output_asset_id = asset.id
                session.flush()

        actual = settlement_credits(
            reserved_credits=job.reserved_credits,
            operation=job.operation,
            requested_duration_seconds=int(params.get("duration_seconds") or 0),
            delivered_duration_ms=result.duration_ms,
        )
        jobs_service.settle_success(session, job, actual_credits=actual)
        job = sm.transition(
            session,
            job.id,
            JobStatus.SUCCEEDED,
            actual_credits=actual,
            output_asset_id=asset.id,
        )
        _emit(
            session,
            job,
            JobEventType.SUCCEEDED,
            JobStatus.SUCCEEDED,
            "生成完成",
            100,
            payload={"asset_id": asset.id},
        )
        return PipelineOutcome(status=JobStatus.SUCCEEDED, asset_id=asset.id)

    _fail(
        session,
        job,
        code=last_failure or "PROVIDER_TEMPORARY_FAILURE",
        message="多次尝试后仍未成功，积分已退回。",
    )
    return PipelineOutcome(status=JobStatus.FAILED, failure_code=last_failure)


def _cancelled(session: Session, job: GenerationJob) -> bool:
    session.refresh(job)
    return job.cancel_requested_at is not None


def _cancel(session: Session, job: GenerationJob) -> PipelineOutcome:
    jobs_service.settle_release(session, job, reason="cancelled_by_user")
    job = sm.transition(session, job.id, JobStatus.CANCELLED)
    _emit(session, job, JobEventType.CANCELLED, JobStatus.CANCELLED, "任务已取消，积分已退回", 100)
    return PipelineOutcome(status=JobStatus.CANCELLED)


def _fail(
    session: Session,
    job: GenerationJob,
    *,
    code: str,
    message: str,
    event_type: JobEventType = JobEventType.FAILED,
) -> None:
    """Terminal failure. Releasing the reservation is not optional."""
    jobs_service.settle_release(session, job, reason=code)
    try:
        job = sm.transition(
            session, job.id, JobStatus.FAILED, failure_code=code, failure_message=message
        )
    except Exception:
        logger.exception("could not mark job %s failed", job.id)
        return
    _emit(session, job, event_type, JobStatus.FAILED, message, 100, internal_code=code)


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
    # Persist first, then notify: a live subscriber and a reconnecting one must
    # see the same sequence.
    session.commit()
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
