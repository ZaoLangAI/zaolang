"""`fast_retry.build_seed`'s eligibility gate for skipping a retry straight to
`route_score`.

Exercises the function directly (constructing rows by hand, like
`test_routing_retry_exclusion.py` does for `execute_route_score`) rather than
through a full pipeline run — this is a property of one gate's decision
logic, not of the graph. `back/tests/integration/test_job_retry.py` covers
the end-to-end wiring (the actual `/retry` call skipping real nodes).
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.domain.jobs import fast_retry
from app.models import GenerationJob, JobEvent, ProviderAttempt, User
from app.models.base import new_id, utcnow
from app.models.enums import (
    ImageAssetKind,
    JobEventType,
    JobStatus,
    Operation,
    ProviderAttemptStatus,
    ProviderKind,
    QualityTier,
)


def _original_job(
    db: Session,
    author: User,
    *,
    failure_code: str | None,
    prompt: str = "雨后的东京街头",
    with_attempt: bool = True,
    with_generating_event: bool = True,
) -> GenerationJob:
    job = GenerationJob(
        id=new_id("job"),
        user_id=author.id,
        operation=Operation.TEXT_TO_IMAGE.value,
        quality_tier=QualityTier.STANDARD.value,
        request_json={"prompt": prompt},
        quoted_credits=0,
        reserved_credits=0,
        idempotency_key=new_id("idk"),
        status=JobStatus.FAILED.value,
        failure_code=failure_code,
    )
    db.add(job)
    db.flush()
    if with_attempt:
        db.add(
            ProviderAttempt(
                id=new_id("atp"),
                job_id=job.id,
                provider="fake_open_workflow",
                provider_kind=ProviderKind.OPEN_WORKFLOW.value,
                model_or_workflow_version="comfy-sdxl-base@1.4.0",
                attempt_number=1,
                status=ProviderAttemptStatus.FAILED.value,
                created_at=utcnow(),
            )
        )
    if with_generating_event:
        db.add(
            JobEvent(
                id=new_id("evt"),
                job_id=job.id,
                sequence=1,
                event_type=JobEventType.GENERATING.value,
                status=JobStatus.SUBMITTED.value,
                progress=40,
                public_message="正在生成",
                payload_json={"prompt": f"{prompt}，增强版", "negative_prompt": "低质量"},
                created_at=utcnow(),
            )
        )
    db.flush()
    return job


def _retry_job(*, original_id: str, request_json: dict[str, object]) -> GenerationJob:
    """A brand-new retry job, deliberately never persisted — `build_seed`
    only ever reads its plain attributes, never queries by its id."""
    return GenerationJob(
        id=new_id("job"),
        user_id="unused",
        operation=Operation.TEXT_TO_IMAGE.value,
        quality_tier=QualityTier.STANDARD.value,
        request_json=request_json,
        quoted_credits=0,
        reserved_credits=0,
        idempotency_key=new_id("idk"),
        retry_of_job_id=original_id,
    )


def test_a_real_provider_failure_yields_a_seed_with_the_resolved_prompt(
    db: Session, author: User
) -> None:
    original = _original_job(db, author, failure_code="PROVIDER_TEMPORARY_FAILURE")
    retry = _retry_job(original_id=original.id, request_json=original.request_json)

    seed = fast_retry.build_seed(db, retry)

    assert seed is not None
    assert seed.prompt == "雨后的东京街头，增强版"
    assert seed.negative_prompt == "低质量"
    assert seed.tried_providers == {"fake_open_workflow"}


def test_not_a_retry_yields_no_seed(db: Session, author: User) -> None:
    plain = _retry_job(original_id="", request_json={"prompt": "无重试来源"})
    plain.retry_of_job_id = None
    assert fast_retry.build_seed(db, plain) is None


def test_an_operation_outside_image_or_video_yields_no_seed(db: Session, author: User) -> None:
    original = _original_job(db, author, failure_code="PROVIDER_TEMPORARY_FAILURE")
    retry = _retry_job(original_id=original.id, request_json=original.request_json)
    retry.operation = Operation.AUDIO_GENERATION.value

    assert fast_retry.build_seed(db, retry) is None


def test_a_safety_rejection_yields_no_seed(db: Session, author: User) -> None:
    """A hard veto must always be re-checked — content unchanged is exactly
    why skipping it here would be wrong, not a reason to skip it."""
    original = _original_job(db, author, failure_code="MODERATION_REJECTED", with_attempt=False)
    retry = _retry_job(original_id=original.id, request_json=original.request_json)

    assert fast_retry.build_seed(db, retry) is None


def test_a_quality_rejection_yields_no_seed(db: Session, author: User) -> None:
    """The provider itself didn't fail — nothing here needs re-routing."""
    original = _original_job(db, author, failure_code="QUALITY_REJECTED")
    retry = _retry_job(original_id=original.id, request_json=original.request_json)

    assert fast_retry.build_seed(db, retry) is None


def test_no_candidate_ever_available_yields_no_seed(db: Session, author: User) -> None:
    """Same code as a real failure (`PROVIDER_TEMPORARY_FAILURE`), but no
    provider was ever actually called — nothing to exclude, nothing gained
    by skipping planning."""
    original = _original_job(
        db, author, failure_code="PROVIDER_TEMPORARY_FAILURE", with_attempt=False
    )
    retry = _retry_job(original_id=original.id, request_json=original.request_json)

    assert fast_retry.build_seed(db, retry) is None


def test_a_missing_reference_failure_yields_no_seed(db: Session, author: User) -> None:
    """A client-input problem — switching providers can't fix it, and the
    unchanged reference will still be missing next time."""
    original = _original_job(db, author, failure_code="MISSING_REFERENCE")
    retry = _retry_job(original_id=original.id, request_json=original.request_json)

    assert fast_retry.build_seed(db, retry) is None


def test_a_character_asset_kind_job_yields_no_seed(db: Session, author: User) -> None:
    """`asset_planning`/`asset_output_advance` depend on per-pass state this
    gate doesn't (and shouldn't) reconstruct — excluded for now."""
    original = _original_job(db, author, failure_code="PROVIDER_TEMPORARY_FAILURE")
    request_json = {**original.request_json, "asset_kind": ImageAssetKind.CHARACTER.value}
    retry = _retry_job(original_id=original.id, request_json=request_json)

    assert fast_retry.build_seed(db, retry) is None


def test_missing_original_job_yields_no_seed(db: Session, author: User) -> None:
    retry = _retry_job(original_id=new_id("job"), request_json={"prompt": "找不到原任务"})
    assert fast_retry.build_seed(db, retry) is None


def test_no_resolved_prompt_event_yields_no_seed(db: Session, author: User) -> None:
    """A job that never even reached `provider_generate`'s own `JobEvent`
    (an older row, or a graph that renamed the event) has nothing safe to
    reuse — falls back to the full pipeline rather than guessing."""
    original = _original_job(
        db,
        author,
        failure_code="PROVIDER_TEMPORARY_FAILURE",
        with_generating_event=False,
    )
    retry = _retry_job(original_id=original.id, request_json=original.request_json)

    assert fast_retry.build_seed(db, retry) is None
