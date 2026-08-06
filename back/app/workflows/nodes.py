"""Node executors: the code-reviewed half of the workflow engine.

Each function here is what a `NodeSpec` in `registry.py` points at. An
operator can rewire *which* of these run and in what order (the graph), but
never *what one of them does* — every credit reservation, state transition
and audit-relevant write lives in this file, not in admin-editable config.
Keep every executor's shape close to the step it replaces in the old
`app.workers.pipeline` module so the two stay easy to compare.
"""

from __future__ import annotations

import logging

from app.agents import intent_router as intent_router_agent
from app.agents import planner, quality, router, safety
from app.domain.credits.pricing import settlement_credits
from app.domain.errors import NotFound
from app.domain.jobs import service as jobs_service
from app.domain.jobs import state_machine as sm
from app.domain.media import service as media_service
from app.domain.notifications import push as notifications
from app.domain.skill_library import service as skill_library_service
from app.models import Draft, ProviderAttempt
from app.models.base import utcnow
from app.models.enums import (
    JobEventType,
    JobStatus,
    ModerationStage,
    ModerationStatus,
    NotificationType,
    ProviderAttemptStatus,
    QualityTier,
)
from app.providers.base import GenerationRequest, GenerationResult
from app.realtime import publisher
from app.workflows.configs import (
    FailConfig,
    IntentRouterConfig,
    JoinConfig,
    PlanningConfig,
    ProviderGenerateConfig,
    QualityCheckConfig,
    RouteScoreConfig,
    SafetyCheckConfig,
    SettleSuccessConfig,
    SkillContextConfig,
)
from app.workflows.types import NodeResult, PipelineOutcome, WorkflowContext

logger = logging.getLogger(__name__)

_TIER_RANK: dict[str, int] = {
    QualityTier.PREVIEW.value: 0,
    QualityTier.STANDARD.value: 1,
    QualityTier.CINEMATIC.value: 2,
}


def _emit(
    ctx: WorkflowContext,
    event_type: JobEventType,
    status: JobStatus,
    message: str,
    progress: int,
    *,
    internal_code: str | None = None,
    payload: dict[str, object] | None = None,
) -> None:
    """Writes a real `JobEvent` and publishes it.

    A no-op during a sandbox dry-run: by design that mode never touches a
    real job's event stream (there is no real job to attach one to).
    """
    if ctx.dry_run:
        return
    event = sm.append_event(
        ctx.session,
        ctx.job.id,
        event_type=event_type,
        status=status,
        public_message=message,
        progress=progress,
        internal_code=internal_code,
        payload=payload,
    )
    if status in (JobStatus.SUCCEEDED, JobStatus.FAILED):
        # 只在终态发通知：进度事件太吵，用户只关心结果。
        notifications.notify(
            ctx.session,
            user_id=ctx.job.user_id,
            type=(
                NotificationType.JOB_SUCCEEDED
                if status == JobStatus.SUCCEEDED
                else NotificationType.JOB_FAILED
            ),
            title_key=(
                "notification.job_succeeded"
                if status == JobStatus.SUCCEEDED
                else "notification.job_failed"
            ),
            payload={"job_id": ctx.job.id},
            target_type="generation_job",
            target_id=ctx.job.id,
        )
    ctx.session.commit()
    publisher.publish_job_event(
        ctx.job.id,
        {
            "sequence": event.sequence,
            "event_type": event.event_type,
            "status": event.status,
            "progress": event.progress,
            "message": event.public_message,
        },
    )


def execute_safety_check(ctx: WorkflowContext, config: SafetyCheckConfig) -> NodeResult:
    _emit(ctx, JobEventType.SAFETY, JobStatus.QUEUED, "正在进行安全检查", 8)
    verdict = safety.review(
        ctx.session,
        text=ctx.prompt,
        stage=ModerationStage.PRE_GENERATION,
        subject_type="generation_job",
        subject_id=ctx.job.id,
        job_id=ctx.agent_job_id,
        user_id=ctx.job.user_id,
    )
    ctx.state["_last_agent_run_id"] = verdict.agent_run_id
    if verdict.status == ModerationStatus.REJECTED:
        # Hard veto: only the `fail` node may act on this, and nothing
        # downstream may override it.
        ctx.state["failure_code"] = "MODERATION_REJECTED"
        ctx.state["failure_message"] = verdict.public_message or "内容未通过安全检查。"
        return NodeResult(port="reject")
    return NodeResult(port="pass")


def execute_skill_context(ctx: WorkflowContext, config: SkillContextConfig) -> NodeResult:
    """Makes a `CreationSkill`'s params authoritative server-side.

    The studio already merges a skill's params into the form locally and
    counts the usage the moment a user picks it (`POST /v1/skills/{id}/apply`
    -> `record_usage`) — that is the popularity signal, and stays a one-shot
    "selected" event independent of whether a job ever gets submitted. This
    node does not call `record_usage` again (that would double-count every
    submission); its job is only to not trust the client's merge: a request
    built without ever calling `/apply` (a future API-only client, a replay)
    still gets the skill's real params rather than silently skipping them.
    """
    skill_id = ctx.params.get("skill_id")
    if not skill_id or ctx.dry_run:
        return NodeResult(port="ok")
    try:
        skill = skill_library_service.get_usable(
            ctx.session, skill_id=str(skill_id), viewer_id=ctx.job.user_id
        )
    except NotFound:
        logger.warning("job %s referenced an unusable skill %s; ignoring", ctx.job.id, skill_id)
        return NodeResult(port="ok")

    # The user's own explicit params always win over the skill's template.
    merged = dict(skill.params_json)
    merged.update({k: v for k, v in ctx.params.items() if k != "skill_id"})
    ctx.params = merged
    return NodeResult(port="ok")


def execute_planning(ctx: WorkflowContext, config: PlanningConfig) -> NodeResult:
    _emit(ctx, JobEventType.PLANNING, JobStatus.QUEUED, "正在规划生成方案", 16)
    outcome = planner.plan(
        ctx.session,
        intent=ctx.prompt,
        source_params=ctx.params,
        requested_operation=ctx.job.operation,
        job_id=ctx.agent_job_id,
        user_id=ctx.job.user_id,
    )
    ctx.state["_last_agent_run_id"] = outcome.agent_run_id
    return NodeResult(port="ok")


def execute_intent_router(ctx: WorkflowContext, config: IntentRouterConfig) -> NodeResult:
    _emit(ctx, JobEventType.INTENT_ROUTING, JobStatus.QUEUED, "正在理解生成意图", 20)
    outcome = intent_router_agent.classify(
        ctx.session,
        intent=ctx.prompt,
        params=ctx.params,
        operation=ctx.job.operation,
        requested_tier=ctx.job.quality_tier,
        job_id=ctx.agent_job_id,
        user_id=ctx.job.user_id,
    )
    ctx.state["intent_hint"] = outcome.data
    ctx.state["_last_agent_run_id"] = outcome.agent_run_id
    return NodeResult(port="ok")


def _effective_tier(requested: str, hint: dict[str, object]) -> str:
    """Applies the intent router's suggestion, but only ever downgrades.

    The user already paid for `requested`; a cost-saving hint may steer them
    to something cheaper, never to a tier they did not ask for.
    """
    suggested = hint.get("suggested_quality_tier")
    if not isinstance(suggested, str) or suggested not in _TIER_RANK or requested not in _TIER_RANK:
        return requested
    return suggested if _TIER_RANK[suggested] < _TIER_RANK[requested] else requested


def execute_route_score(ctx: WorkflowContext, config: RouteScoreConfig) -> NodeResult:
    attempts = ctx.state.get("route_attempts", 0) + 1
    ctx.state["route_attempts"] = attempts
    if attempts > config.max_attempts:
        return NodeResult(port="retries_exhausted")
    ctx.state["attempt_number"] = attempts

    _emit(ctx, JobEventType.ROUTING, JobStatus.QUEUED, "正在选择生成路线", 24)

    # A retry that got here because the *provider* actually failed (not a
    # quality-check rejection, which is not evidence the provider itself is
    # bad) must not be handed straight back to the LLM as if nothing
    # happened — it would very plausibly pick the same one again. A
    # quality-check retry keeps the provider eligible: nothing about it
    # failed.
    tried_providers: set[str] = ctx.state.setdefault("tried_providers", set())
    prior_decision = ctx.state.get("decision")
    if (
        prior_decision is not None
        and prior_decision.selected is not None
        and ctx.state.get("failure_code") not in (None, "QUALITY_REJECTED")
    ):
        tried_providers.add(prior_decision.selected.provider)

    hint = ctx.state.get("intent_hint") or {}
    tier = _effective_tier(ctx.job.quality_tier, hint)
    decision = router.route(
        ctx.session,
        operation=ctx.job.operation,
        quality_tier=tier,
        max_latency_ms=config.max_latency_ms,
        exclude_providers=tried_providers,
        job_id=ctx.agent_job_id,
        user_id=ctx.job.user_id,
    )
    ctx.job.routing_trace_json = decision.trace()
    ctx.session.flush()

    if decision.selected is None or decision.capability is None:
        ctx.state["failure_code"] = "PROVIDER_TEMPORARY_FAILURE"
        ctx.state["failure_message"] = "暂时没有可用的生成路线，积分已退回。"
        return NodeResult(port="no_candidate")

    ctx.state["decision"] = decision
    capability = decision.capability
    ctx.job.selected_route_summary_json = {
        "provider": capability.name,
        "provider_kind": capability.kind.value,
        "model_or_workflow": capability.model_or_workflow,
        "reason": decision.reason,
    }
    ctx.session.flush()
    return NodeResult(port="ok")


def execute_provider_generate(ctx: WorkflowContext, config: ProviderGenerateConfig) -> NodeResult:
    decision = ctx.state.get("decision")
    if decision is None or decision.capability is None:
        # Only reachable if a custom graph wires this node without a
        # preceding `route_score` — an operator authoring error, not
        # something worth guessing our way past.
        ctx.state["failure_code"] = "PROVIDER_TEMPORARY_FAILURE"
        ctx.state["failure_message"] = "没有可用的生成路线，积分已退回。"
        return NodeResult(port="failed")

    capability = decision.capability
    attempt_number = ctx.state.get("attempt_number", 1)

    if ctx.dry_run:
        _emit(ctx, JobEventType.GENERATING, JobStatus.SUBMITTED, "正在生成", 40)
        result = GenerationResult(
            succeeded=True,
            object_key="dry-run/stub.png",
            mime_type="image/png",
            width=1024,
            height=576,
            duration_ms=0,
            cost_minor=0,
            latency_ms=0,
            metadata={"dry_run": True},
        )
    else:
        # A retry re-enters with the job already `running`; the state
        # machine rightly refuses running -> running.
        if ctx.job.status == JobStatus.QUEUED:
            ctx.job = sm.transition(ctx.session, ctx.job.id, JobStatus.SUBMITTED)
        _emit(ctx, JobEventType.GENERATING, JobStatus.SUBMITTED, "正在生成", 40)
        if ctx.job.status != JobStatus.RUNNING:
            ctx.job = sm.transition(ctx.session, ctx.job.id, JobStatus.RUNNING)

        ctx.session.refresh(ctx.job)
        if ctx.job.cancel_requested_at is not None:
            jobs_service.settle_release(ctx.session, ctx.job, reason="cancelled_by_user")
            ctx.job = sm.transition(ctx.session, ctx.job.id, JobStatus.CANCELLED)
            _emit(ctx, JobEventType.CANCELLED, JobStatus.CANCELLED, "任务已取消，积分已退回", 100)
            return NodeResult(
                port="cancelled", terminal=PipelineOutcome(status=JobStatus.CANCELLED)
            )

        result = decision.provider.submit(
            GenerationRequest(
                job_id=ctx.job.id,
                operation=ctx.job.operation,
                quality_tier=ctx.job.quality_tier,
                prompt=ctx.prompt,
                negative_prompt=ctx.params.get("negative_prompt"),
                seed=ctx.params.get("seed"),
                aspect_ratio=str(ctx.params.get("aspect_ratio") or "16:9"),
                duration_seconds=int(ctx.params.get("duration_seconds") or 0),
                reference_object_keys=media_service.object_keys_for(
                    ctx.session, asset_ids=ctx.params.get("reference_asset_ids") or []
                ),
                extra=dict(ctx.params.get("extra") or {}),
            )
        )
        ctx.session.add(
            ProviderAttempt(
                job_id=ctx.job.id,
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
            ctx.session,
            provider=capability.name,
            operation=ctx.job.operation,
            quality_tier=ctx.job.quality_tier,
            succeeded=result.succeeded,
            latency_ms=result.latency_ms,
            cost_minor=result.cost_minor,
        )
        ctx.session.flush()

    if not result.succeeded or result.object_key is None:
        ctx.state["failure_code"] = result.failure_code or "PROVIDER_TEMPORARY_FAILURE"
        _emit(
            ctx,
            JobEventType.PROGRESS,
            JobStatus.RUNNING,
            "这条线路暂时不可用，正在尝试其他路线",
            45,
            internal_code=ctx.state["failure_code"],
        )
        if not config.retry_on_failure:
            ctx.state["failure_message"] = "生成失败，积分已退回。"
            return NodeResult(port="failed")
        return NodeResult(port="retry")

    ctx.state["result"] = result
    ctx.state["capability"] = capability
    return NodeResult(port="succeeded")


def execute_quality_check(ctx: WorkflowContext, config: QualityCheckConfig) -> NodeResult:
    result = ctx.state.get("result")
    capability = ctx.state.get("capability")
    attempt_number = ctx.state.get("attempt_number", 1)

    _emit(ctx, JobEventType.QUALITY_CHECK, JobStatus.RUNNING, "正在校验输出质量", 78)
    outcome = quality.evaluate(
        ctx.session,
        prompt=ctx.prompt,
        output_summary={
            "width": result.width if result else None,
            "height": result.height if result else None,
            "duration_ms": result.duration_ms if result else None,
            "provider": capability.name if capability else None,
        },
        attempt_number=attempt_number,
        job_id=ctx.agent_job_id,
        user_id=ctx.job.user_id,
    )
    ctx.state["_last_agent_run_id"] = outcome.agent_run_id

    if outcome.data.get("verdict") == "fail":
        ctx.state["failure_code"] = "QUALITY_REJECTED"
        if outcome.data.get("should_retry"):
            _emit(
                ctx,
                JobEventType.PROGRESS,
                JobStatus.RUNNING,
                "输出质量不理想，正在重新生成",
                50,
                internal_code="QUALITY_REJECTED",
            )
            return NodeResult(port="retry")
        ctx.state["failure_message"] = "生成结果未通过质量校验，积分已退回。"
        return NodeResult(port="fail")

    if ctx.dry_run or result is None or capability is None:
        ctx.state["asset_id"] = None
        ctx.state["actual_credits"] = 0
        return NodeResult(port="pass")

    asset = media_service.register_generated_asset(
        ctx.session,
        owner_user_id=ctx.job.user_id,
        object_key=result.object_key,
        mime_type=result.mime_type,
        width=result.width,
        height=result.height,
        duration_ms=result.duration_ms,
        generation_job_id=ctx.job.id,
        provenance={
            "provider": capability.name,
            "model_or_workflow": capability.model_or_workflow,
            "operation": ctx.job.operation,
            "quality_tier": ctx.job.quality_tier,
        },
    )
    if ctx.job.draft_id:
        draft = ctx.session.get(Draft, ctx.job.draft_id)
        if draft is not None:
            draft.output_asset_id = asset.id
            ctx.session.flush()

    ctx.state["asset_id"] = asset.id
    ctx.state["actual_credits"] = settlement_credits(
        reserved_credits=ctx.job.reserved_credits,
        operation=ctx.job.operation,
        requested_duration_seconds=int(ctx.params.get("duration_seconds") or 0),
        delivered_duration_ms=result.duration_ms,
    )
    return NodeResult(port="pass")


def execute_join(ctx: WorkflowContext, config: JoinConfig) -> NodeResult:
    """Combines the (sequentially executed — see `runner.py`) branch results
    the runner collected for this join."""
    branch_results: list[NodeResult] = ctx.state.pop("_branch_results", [])
    if not branch_results:
        return NodeResult(port="ok")
    matcher = any if config.mode == "race" else all
    if matcher(r.port in config.success_ports for r in branch_results):
        return NodeResult(port="ok")
    return NodeResult(port="partial_failure")


def execute_settle_success(ctx: WorkflowContext, config: SettleSuccessConfig) -> NodeResult:
    asset_id = ctx.state.get("asset_id")
    terminal = PipelineOutcome(status=JobStatus.SUCCEEDED, asset_id=asset_id)
    if ctx.dry_run:
        return NodeResult(port="_terminal", terminal=terminal)

    actual = ctx.state.get("actual_credits")
    if actual is None:
        actual = ctx.job.reserved_credits
    jobs_service.settle_success(ctx.session, ctx.job, actual_credits=actual)
    ctx.job = sm.transition(
        ctx.session,
        ctx.job.id,
        JobStatus.SUCCEEDED,
        actual_credits=actual,
        output_asset_id=asset_id,
    )
    _emit(
        ctx,
        JobEventType.SUCCEEDED,
        JobStatus.SUCCEEDED,
        "生成完成",
        100,
        payload={"asset_id": asset_id},
    )
    return NodeResult(port="_terminal", terminal=terminal)


def execute_fail(ctx: WorkflowContext, config: FailConfig) -> NodeResult:
    code = ctx.state.get("failure_code") or config.default_code
    message = ctx.state.get("failure_message") or config.default_message

    terminal = PipelineOutcome(status=JobStatus.FAILED, failure_code=code)
    if ctx.dry_run:
        return NodeResult(port="_terminal", terminal=terminal)

    jobs_service.settle_release(ctx.session, ctx.job, reason=code)
    try:
        ctx.job = sm.transition(
            ctx.session, ctx.job.id, JobStatus.FAILED, failure_code=code, failure_message=message
        )
    except Exception:
        logger.exception("could not mark job %s failed", ctx.job.id)
        return NodeResult(port="_terminal", terminal=terminal)
    _emit(ctx, JobEventType.FAILED, JobStatus.FAILED, message, 100, internal_code=code)
    return NodeResult(port="_terminal", terminal=terminal)
