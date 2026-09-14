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
from app.domain.consent import service as consent_service
from app.domain.credits import service as credits_service
from app.domain.credits.pricing import Quote
from app.domain.credits.pricing import quote as compute_quote
from app.domain.errors import (
    Conflict,
    CreditsExceedBudget,
    IdempotencyConflict,
    InsufficientCredits,
    NotFound,
    SpendLimitExceeded,
)
from app.domain.jobs import state_machine as sm
from app.domain.media import service as media_service
from app.domain.notifications import push as notifications
from app.domain.scenes import service as scenes_service
from app.domain.shortform import service as shortform_service
from app.domain.workflow_templates import service as workflow_templates_service
from app.models import Draft, GenerationJob, JobEvent
from app.models.enums import ImageAssetKind, JobEventType, JobOrigin, JobStatus, VideoAssetKind
from app.platform_config import service as config_service
from app.platform_config.schemas import PricingConfig

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class SubmissionResult:
    job: GenerationJob
    quote: Quote
    replayed: bool = False


def quote_for(
    session: Session,
    *,
    operation: str,
    quality_tier: str,
    duration_seconds: int = 0,
    output_count: int = 1,
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
        output_count=output_count,
    )


# `apply_character_refs`/`apply_scene_refs` (called later in `submit`) only
# ever merge into these two keys, so a request that is otherwise identical
# except for server-side reference-merging must not look like a body
# mismatch below.
_MUTATED_PARAM_KEYS = frozenset({"reference_asset_ids", "extra"})


def _is_replay_of(
    existing: GenerationJob, *, operation: str, quality_tier: str, params: dict[str, Any]
) -> bool:
    """True when a reused idempotency key is replaying the same request.

    Compares the fields that define what the job actually does, not merely
    that the key matches — a client that reuses a key with a materially
    different body (a different prompt, operation, or tier) must get
    `IdempotencyConflict`, not the first request's unrelated job silently
    handed back.
    """
    if existing.operation != operation or existing.quality_tier != quality_tier:
        return False
    stored = existing.request_json if isinstance(existing.request_json, dict) else {}
    return all(
        stored.get(key) == value for key, value in params.items() if key not in _MUTATED_PARAM_KEYS
    )


def character_output_count(*, asset_kind: str | None, character_views: list[Any] | None) -> int:
    """How many images one job's `character_views` actually asks for.

    `1` for everything except an `asset_kind=character` job that named more
    than one view — the only case `GenerationParams.character_views` is ever
    longer than one entry (a "补全侧面/背面" completion request).
    """
    if asset_kind != ImageAssetKind.CHARACTER.value or not character_views:
        return 1
    return len(character_views)


def skips_credits(job: GenerationJob) -> bool:
    """Sandbox try-its persist a real job but never touch the credit ledger."""
    return job.origin == JobOrigin.SANDBOX


def _point_draft_at_job(
    session: Session,
    *,
    user_id: str,
    draft_id: str | None,
    job_id: str,
    sandbox: bool,
) -> None:
    """Keeps `Draft.latest_job_id` on the job just submitted.

    Image-studio resume (and any other `?draftId=` entry) only has this
    pointer — create, retry, and promote must all advance it, or a
    notification click reopens the previous (often failed) attempt.

    A character/scene job also copies `asset_kind` onto `Draft.params_json`
    so resume surfaces can tell a roster generation from a general image
    without waiting for the client to persist that key (iOS create-then-
    submit; the window after `POST /drafts` and before this pointer lands).
    """
    if sandbox or not draft_id:
        return
    draft = session.get(Draft, draft_id)
    if draft is None or draft.user_id != user_id:
        return
    draft.latest_job_id = job_id
    job = session.get(GenerationJob, job_id)
    if job is None:
        return
    kind = (job.request_json or {}).get("asset_kind")
    if kind not in {ImageAssetKind.CHARACTER.value, ImageAssetKind.SCENE.value}:
        return
    params = dict(draft.params_json or {})
    if params.get("asset_kind") == kind:
        return
    params["asset_kind"] = kind
    draft.params_json = params


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
    origin: str = JobOrigin.USER,
    graph_override_json: dict[str, Any] | None = None,
) -> SubmissionResult:
    """Creates a job and reserves its credits.

    The unique `(user_id, idempotency_key)` index is what makes a double-tapped
    submit button produce one job rather than two reservations.

    `origin=sandbox` still quotes (so ops can see what the run would have
    cost) but skips the balance check and the reservation. `graph_override_json`
    is the unpublished canvas snapshot a sandbox try-it walks — it is stored
    on the job and must not pin the live template.

    When `draft_id` names an owned draft, `Draft.latest_job_id` is pointed at
    this job (including an idempotent replay) so create / retry / promote
    share one pointer instead of each route writing it by hand.
    """
    existing = session.scalar(
        select(GenerationJob).where(
            GenerationJob.user_id == user_id,
            GenerationJob.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        if not _is_replay_of(
            existing, operation=operation, quality_tier=quality_tier, params=params
        ):
            raise IdempotencyConflict()
        _point_draft_at_job(
            session,
            user_id=user_id,
            draft_id=existing.draft_id or draft_id,
            job_id=existing.id,
            sandbox=skips_credits(existing),
        )
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
    characters_service.apply_character_refs(
        session, user_id=user_id, params=params, operation=operation
    )
    scenes_service.apply_scene_refs(session, user_id=user_id, params=params)
    media_service.attach_licensed_source_video(
        session, params=params, source_work_version_id=source_work_version_id
    )
    media_service.validate_generation_references(
        session,
        user_id=user_id,
        operation=operation,
        params=params,
        source_work_version_id=source_work_version_id,
    )
    # A voice-clone sample or a real-person reference needs that person's
    # consent (深度合成管理规定 §14). Checked before quoting, like the
    # ownership check above, so a missing consent never reserves credits.
    consent_service.assert_reference_consents(session, operation=operation, params=params)
    shortform_service.assert_params_consistent(session, params)

    priced = quote_for(
        session,
        operation=operation,
        quality_tier=quality_tier,
        duration_seconds=int(params.get("duration_seconds") or 0),
        output_count=character_output_count(
            asset_kind=params.get("asset_kind"), character_views=params.get("character_views")
        ),
    )
    sandbox = origin == JobOrigin.SANDBOX
    if not sandbox and max_credits is not None and priced.credits > max_credits:
        raise CreditsExceedBudget(
            f"预计消耗 {priced.credits} 积分，超过你设置的 {max_credits} 上限。",
            quoted=priced.credits,
            max_credits=max_credits,
        )

    if not sandbox:
        account = credits_service.get_or_create_account(session, user_id)
        if account.available_balance < priced.credits:
            raise InsufficientCredits(
                f"需要 {priced.credits} 积分，当前可用 {account.available_balance}。",
                required=priced.credits,
                available=account.available_balance,
            )
        # Checked before the job row exists so an over-cap submit costs
        # nothing; `reserve` enforces the same cap again inside its UPDATE.
        remaining = credits_service.remaining_monthly_spend(account)
        if remaining is not None and remaining < priced.credits:
            raise SpendLimitExceeded(
                f"需要 {priced.credits} 积分，本月消费上限还剩 {remaining}。",
                required=priced.credits,
                remaining=remaining,
            )

    # Pinned now, not resolved lazily at run time: a template published while
    # this job sits in the queue must not change what it runs. Left `None`
    # when nothing has ever been published for the operation yet (fresh
    # deploy before `make seed`) — `pipeline._resolve_graph` falls back to
    # the code-level default graph for those. A sandbox draft snapshot must
    # not pin (or later backfill) the live template, or a publish mid-run
    # would change what the try-it walked.
    # Whichever of the two orthogonal asset-kind axes is actually meaningful
    # for this job's operation — `validate_generation_params` already
    # guarantees at most one of them is non-`GENERAL` (image kinds are
    # rejected outside `IMAGE_OPERATIONS`, video kinds outside
    # `VIDEO_OPERATIONS`), so checking the video field first and falling back
    # to the image field is safe: a video job's `asset_kind` is always still
    # sitting at its `GENERAL` default. `get_active` itself already treats a
    # `"general"` value the same as `None` (see its own `normalized` check).
    raw_video_kind = params.get("video_asset_kind")
    asset_kind = (
        raw_video_kind
        if isinstance(raw_video_kind, str) and raw_video_kind != VideoAssetKind.GENERAL.value
        else (params.get("asset_kind") if isinstance(params.get("asset_kind"), str) else None)
    )
    active_template = (
        None
        if graph_override_json
        else workflow_templates_service.get_active(session, operation, asset_kind)
    )

    job = GenerationJob(
        user_id=user_id,
        draft_id=draft_id,
        source_work_version_id=source_work_version_id,
        operation=operation,
        request_json=params,
        quality_tier=quality_tier,
        status=JobStatus.CREATED,
        origin=origin,
        quoted_credits=priced.credits,
        reserved_credits=0 if sandbox else priced.credits,
        max_credits=max_credits,
        idempotency_key=idempotency_key,
        estimated_seconds=priced.estimated_seconds,
        workflow_template_id=active_template.id if active_template else None,
        graph_override_json=graph_override_json,
    )
    session.add(job)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise Conflict("相同请求正在处理中。") from exc

    if not sandbox:
        credits_service.reserve(session, user_id, priced.credits, job_id=job.id)
    sm.append_event(
        session,
        job.id,
        event_type=JobEventType.QUEUED,
        status=JobStatus.CREATED,
        public_message="任务已创建，正在排队。",
        progress=2,
    )
    if not sandbox:
        notifications.sync_job_notification(session, job)
    _point_draft_at_job(
        session,
        user_id=user_id,
        draft_id=draft_id,
        job_id=job.id,
        sandbox=sandbox,
    )
    return SubmissionResult(job=job, quote=priced)


def settle_success(session: Session, job: GenerationJob, *, actual_credits: int) -> None:
    """Captures the reservation and returns any unused portion."""
    if skips_credits(job):
        job.actual_credits = 0
        return
    credits_service.capture(session, job.user_id, job_id=job.id, actual_amount=actual_credits)


def settle_release(session: Session, job: GenerationJob, *, reason: str) -> None:
    """Returns the reservation in full.

    Safe to call more than once: an already-settled job is left untouched
    rather than raising, because the retry paths that call this cannot always
    know whether an earlier attempt got that far.
    """
    if skips_credits(job):
        return
    try:
        credits_service.release(session, job.user_id, job_id=job.id, reason=reason)
    except Conflict:
        logger.info("job %s reservation already settled", job.id)


SANDBOX_PROMPT_EXCERPT_MAX = 120


def list_sandbox_runs(
    session: Session,
    *,
    operation: str,
    cursor: str | None = None,
    limit: int = 50,
) -> tuple[list[GenerationJob], bool]:
    """Newest-first sandbox try-its for one operation.

    C-end jobs and other operations are out of scope — the editor's history
    is "what did we try against this graph", not the ops job console.
    """
    stmt = (
        select(GenerationJob)
        .where(
            GenerationJob.origin == JobOrigin.SANDBOX,
            GenerationJob.operation == operation,
        )
        .order_by(GenerationJob.created_at.desc(), GenerationJob.id.desc())
    )
    if cursor:
        stmt = stmt.where(GenerationJob.id < cursor)
    rows = list(session.scalars(stmt.limit(limit + 1)))
    has_more = len(rows) > limit
    return rows[:limit], has_more


def sandbox_prompt_excerpt(job: GenerationJob, *, max_len: int = SANDBOX_PROMPT_EXCERPT_MAX) -> str:
    raw = job.request_json.get("prompt") if isinstance(job.request_json, dict) else None
    if not isinstance(raw, str):
        return ""
    return raw.strip()[:max_len]


def get_owned_job(session: Session, job_id: str, user_id: str) -> GenerationJob:
    job = session.get(GenerationJob, job_id)
    # Sandbox try-its belong to the operator but must not surface on the
    # C-end job list or be cancelled/retried through consumer endpoints.
    if job is None or job.user_id != user_id or job.origin == JobOrigin.SANDBOX:
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


def progress_for_batch(session: Session, jobs: list[GenerationJob]) -> dict[str, int]:
    """Batched `progress_for` for list responses: one `DISTINCT ON` query for
    every non-terminal job in the page instead of one `ORDER BY ... LIMIT 1`
    per row."""
    result = {job.id: 100 for job in jobs if JobStatus(job.status).is_terminal}
    pending_ids = [job.id for job in jobs if job.id not in result]
    if not pending_ids:
        return result

    rows = session.execute(
        select(JobEvent.job_id, JobEvent.progress)
        .where(JobEvent.job_id.in_(pending_ids))
        .order_by(JobEvent.job_id, JobEvent.sequence.desc())
        .distinct(JobEvent.job_id)
    )
    for job_id, progress in rows:
        result[job_id] = int(progress or 0)
    for job_id in pending_ids:
        result.setdefault(job_id, 0)
    return result
