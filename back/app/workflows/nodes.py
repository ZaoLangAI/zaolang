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
import time
from dataclasses import asdict
from typing import Any

from app.agents import copywriter, planner, quality, router, safety
from app.agents import custom as custom_agent
from app.agents import intent_router as intent_router_agent
from app.config import get_settings
from app.domain.credits.pricing import settlement_credits
from app.domain.errors import NotFound
from app.domain.jobs import service as jobs_service
from app.domain.jobs import state_machine as sm
from app.domain.jobs.cancellation import honor_user_cancel
from app.domain.media import service as media_service
from app.domain.moderation_queue import service as moderation_queue
from app.domain.skill_library import service as skill_library_service
from app.domain.style_gallery import service as style_gallery_service
from app.models import Draft, ProviderAttempt
from app.models.base import utcnow
from app.models.enums import (
    JobEventType,
    JobStatus,
    ModerationStage,
    ModerationStatus,
    Operation,
    ProviderAttemptStatus,
    QualityTier,
)
from app.providers.base import GenerationProvider, GenerationRequest, GenerationResult
from app.realtime import publisher
from app.storage import s3
from app.workflows.configs import (
    CopyGenerateConfig,
    CustomAgentStepConfig,
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

_VIDEO_OPERATIONS = frozenset(
    {
        Operation.TEXT_TO_VIDEO.value,
        Operation.IMAGE_TO_VIDEO.value,
        Operation.VIDEO_TO_VIDEO.value,
    }
)
_REFERENCE_REQUIRED = frozenset(
    {
        Operation.IMAGE_TO_IMAGE.value,
        Operation.IMAGE_TO_VIDEO.value,
        Operation.VIDEO_TO_VIDEO.value,
    }
)
_SANDBOX_POLL_INTERVAL_SECONDS = 2.0
_SANDBOX_POLL_CAP_MS = 120_000


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

    A no-op when `ctx.dry_run` is set: unit tests walk a graph without a
    persisted job, so there is no event stream to attach one to.
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
        node_id=ctx.state.get("_current_node_id"),
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
            "node_id": event.node_id,
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
        agent_id=config.agent_id,
    )
    ctx.state["_last_agent_run_id"] = verdict.agent_run_id
    if verdict.status == ModerationStatus.REJECTED:
        # Hard veto: only the `fail` node may act on this, and nothing
        # downstream may override it.
        ctx.state["failure_code"] = "MODERATION_REJECTED"
        ctx.state["failure_message"] = verdict.public_message or "内容未通过安全检查。"
        return NodeResult(port="reject", summary=f"拒绝：{verdict.public_message or '未通过'}")
    if verdict.status == ModerationStatus.NEEDS_REVIEW and not ctx.dry_run:
        # Uncertain, not unsafe enough to hard-block: the job still runs, but
        # a human now has something to look at instead of the verdict being
        # recorded and never followed up on. Unit-test dry-runs still skip
        # this because they have no persisted job id; a product sandbox job
        # is a real row and must enqueue like a C-end request.
        moderation_queue.enqueue_for_review(
            ctx.session,
            subject_type="generation_job",
            subject_id=ctx.job.id,
            stage=ModerationStage.PRE_GENERATION,
            reason_code=verdict.reason_code,
            categories=verdict.categories_json.get("categories"),
        )
    return NodeResult(port="pass", summary="通过")


_CONTEXT_ID_KEYS = frozenset({"skill_ids", "style_gallery_id"})


def _fold_params_prompt(prompt: str, params_json: dict[str, Any]) -> str:
    """Applies a template's prompt the same way the studio's local
    `applyParams` does (`front/src/components/studio/generation-studio.tsx`):
    `prompt` is the template's full directive text, `prompt_suffix` is a
    fragment meant to be tacked on. Appending only when the text is not
    already present keeps the normal path (client already merged it via
    `/apply`, possibly user-edited) from getting it duplicated, while a bare
    API call that never merged locally still ends up with it in the final
    prompt sent to the provider.

    Shared by creation skills and system style-gallery entries — both store
    the same `params_json` shape.
    """
    for key in ("prompt", "prompt_suffix"):
        value = params_json.get(key)
        if isinstance(value, str) and value.strip() and value not in prompt:
            return f"{prompt}，{value}" if prompt else value
    return prompt


def execute_skill_context(ctx: WorkflowContext, config: SkillContextConfig) -> NodeResult:
    """Makes applied style-gallery and `CreationSkill` params authoritative.

    The studio already merges templates into the form locally and counts
    usage the moment a user picks one (`POST /v1/skills/{id}/apply` /
    `POST /v1/style-gallery/{id}/apply`) — that is the popularity signal,
    and stays a one-shot "selected" event independent of whether a job ever
    gets submitted. This node does not call those counters again (that would
    double-count every submission); its job is only to not trust the client's
    merge: a request built without ever calling `/apply` (a future API-only
    client, a replay) still gets each template's real params rather than
    silently skipping them — including prompt text, which lives on
    `ctx.prompt` rather than `ctx.params` and so needs its own fold (see
    `_fold_params_prompt`).

    Order: the style gallery entry first (one, mutually exclusive), then
    `skill_ids` in pick order. Later templates win on conflicting keys;
    the user's own explicit params (non-`None`) always win over every
    template. A skill whose `applicable_operations` doesn't include this
    job's operation is skipped, same as an unusable/missing skill or style.
    """
    style_gallery_id = ctx.params.get("style_gallery_id")
    skill_ids = ctx.params.get("skill_ids") or []
    if ctx.dry_run or (not style_gallery_id and not skill_ids):
        return NodeResult(port="ok")

    template_params: dict[str, Any] = {}
    if style_gallery_id:
        try:
            entry = style_gallery_service.get_usable(ctx.session, entry_id=str(style_gallery_id))
        except NotFound:
            logger.warning(
                "job %s referenced an unusable style gallery entry %s; ignoring",
                ctx.job.id,
                style_gallery_id,
            )
        else:
            ctx.prompt = _fold_params_prompt(ctx.prompt, entry.params_json)
            template_params.update(entry.params_json)

    for skill_id in skill_ids:
        try:
            skill = skill_library_service.get_usable(
                ctx.session, skill_id=str(skill_id), viewer_id=ctx.job.user_id
            )
        except NotFound:
            logger.warning("job %s referenced an unusable skill %s; ignoring", ctx.job.id, skill_id)
            continue
        declared = skill.applicable_operations_json
        if declared and ctx.job.operation not in declared:
            logger.warning(
                "job %s skill %s does not apply to operation %s; ignoring",
                ctx.job.id,
                skill_id,
                ctx.job.operation,
            )
            continue
        ctx.prompt = _fold_params_prompt(ctx.prompt, skill.params_json)
        template_params.update(skill.params_json)

    if not template_params:
        return NodeResult(port="ok")

    # The user's own explicit params always win over every template. `None`
    # is how Pydantic `model_dump()` represents omitted optional fields
    # (`negative_prompt: null`) — those must not wipe a template value.
    merged = dict(template_params)
    merged.update(
        {k: v for k, v in ctx.params.items() if k not in _CONTEXT_ID_KEYS and v is not None}
    )
    merged["prompt"] = ctx.prompt
    ctx.params = merged
    return NodeResult(port="ok")


PLAN_STATE_KEY = "plan"


def execute_planning(ctx: WorkflowContext, config: PlanningConfig) -> NodeResult:
    """Runs the planner agent's plan slot, optionally pausing for a follow-up.

    The plan always runs and lands in `ctx.state[config.output_key]` —
    `execute_provider_generate` reads it back under the `PLAN_STATE_KEY`
    convention (which is also `PlanningConfig.output_key`'s default) to fold
    `prompt_enhancements` / `negative_prompt_suggestions` into the actual
    generation request. Same "does not decide the job's fate on its own,
    except by suspending" contract as `execute_copy_generate`: suspending to
    `AWAITING_INPUT` is the one thing that changes the job's status, and only
    when `allow_followup_question` is set and the planner's own `clarify`
    slot judges the intent worth asking about.
    """
    _emit(ctx, JobEventType.PLANNING, JobStatus.QUEUED, "正在规划生成方案", 16)
    outcome = planner.plan(
        ctx.session,
        intent=ctx.prompt,
        source_params=ctx.params,
        requested_operation=ctx.job.operation,
        job_id=ctx.agent_job_id,
        user_id=ctx.job.user_id,
        agent_id=config.agent_id,
    )
    ctx.state[config.output_key] = outcome.data
    ctx.state["_last_agent_run_id"] = outcome.agent_run_id

    if not config.allow_followup_question or ctx.dry_run:
        return NodeResult(port="ok", summary=f"生成计划 → {config.output_key}")

    clarify_outcome = planner.clarify(
        ctx.session,
        intent=ctx.prompt,
        job_id=ctx.agent_job_id,
        user_id=ctx.job.user_id,
        agent_id=config.agent_id,
    )
    ctx.state["_last_agent_run_id"] = clarify_outcome.agent_run_id
    questions = clarify_outcome.data.get("questions") or []
    if not clarify_outcome.data.get("needs_clarification") or not questions:
        return NodeResult(port="ok", summary=f"生成计划 → {config.output_key}（无需追问）")

    # Folded into the checkpoint's `output_value` (via `ctx.state` below) so a
    # resumed run can still render "what was asked" alongside "what was
    # answered" when `_plan_enhancements` builds the effective prompt.
    ctx.state[config.output_key] = {**ctx.state[config.output_key], "clarify_questions": questions}

    _emit(
        ctx,
        JobEventType.AWAITING_INPUT,
        JobStatus.AWAITING_INPUT,
        "规划智能体有几个问题需要你确认，请回答后继续",
        18,
        payload={"question_count": len(questions)},
    )
    return NodeResult(
        port="ok",
        suspend=True,
        checkpoint=_input_checkpoint(ctx, output_key=config.output_key, questions=questions),
        summary=f"暂停等待追问：{len(questions)} 个问题",
    )


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
        agent_id=config.agent_id,
    )
    ctx.state["intent_hint"] = outcome.data
    ctx.state["_last_agent_run_id"] = outcome.agent_run_id
    suggested = outcome.data.get("suggested_quality_tier")
    return NodeResult(port="ok", summary=f"建议档位：{suggested}" if suggested else None)


def execute_custom_agent_step(ctx: WorkflowContext, config: CustomAgentStepConfig) -> NodeResult:
    """Runs an operator-created judgment role and parks its output.

    The single port is the point: a role that shipped without a code review
    may inform a later node, but it may not decide the job's fate on its
    own. Nothing here settles credits or transitions state.
    """
    _emit(ctx, JobEventType.PROGRESS, JobStatus.RUNNING, "正在进行智能体判断", 30)
    outcome = custom_agent.judge(
        ctx.session,
        role=config.agent_role,
        payload={"prompt": ctx.prompt, "params": ctx.params, "operation": ctx.job.operation},
        job_id=ctx.agent_job_id,
        user_id=ctx.job.user_id,
        agent_id=config.agent_id,
        slot=config.slot,
    )
    ctx.state[config.output_key] = outcome.data
    ctx.state["_last_agent_run_id"] = outcome.agent_run_id
    return NodeResult(port="ok", summary=f"{config.agent_role} → {config.output_key}")


def _input_checkpoint(
    ctx: WorkflowContext, *, output_key: str, questions: list[dict[str, object]]
) -> dict[str, object]:
    """The slice of `ctx.state` a resumed run cannot rebuild for itself.

    Mirrors `_provider_checkpoint`'s shape (same four routing-progress keys)
    so `POST /v1/generation-jobs/{id}/answer` (and the admin
    `POST /v1/admin/jobs/{id}/answer`) can rebuild a `WorkflowContext`
    the same way `async_polling._context` does, whichever kind of suspension
    it is resuming from. `output_value` additionally carries this node's own
    first-pass output, since unlike a provider render there is nothing to
    re-fetch — the suggestion already happened, only the questions are new.
    """
    return {
        "kind": "input_request",
        "output_key": output_key,
        "questions": questions,
        "state": {
            "output_value": ctx.state.get(output_key) or {},
            "attempt_number": ctx.state.get("attempt_number", 1),
            "route_attempts": ctx.state.get("route_attempts", 1),
            "tried_providers": sorted(ctx.state.get("tried_providers") or ()),
            "intent_hint": ctx.state.get("intent_hint") or {},
        },
    }


def execute_copy_generate(ctx: WorkflowContext, config: CopyGenerateConfig) -> NodeResult:
    """Runs the copy agent's suggestion, optionally pausing for a follow-up.

    Single port, the same "does not decide the job's fate" contract as
    `custom_agent`: whatever lands in `ctx.state[output_key]` only matters to
    whichever downstream node reads it. Suspending is the one thing that does
    change the job's status — to `AWAITING_INPUT`, resumed by
    `POST /v1/generation-jobs/{id}/answer` — and only when
    `allow_followup_question` is set and the copy agent's own `clarify` slot
    judges the description worth asking about.
    """
    outcome = copywriter.suggest(
        ctx.session,
        prompt=ctx.prompt,
        lineage_summary=str(ctx.params.get("lineage_summary") or ""),
        user_id=ctx.job.user_id,
        agent_id=config.agent_id,
    )
    ctx.state[config.output_key] = outcome.data
    ctx.state["_last_agent_run_id"] = outcome.agent_run_id

    if not config.allow_followup_question or ctx.dry_run:
        return NodeResult(port="ok", summary=f"文案建议 → {config.output_key}")

    clarify_outcome = copywriter.clarify(
        ctx.session, prompt=ctx.prompt, user_id=ctx.job.user_id, agent_id=config.agent_id
    )
    ctx.state["_last_agent_run_id"] = clarify_outcome.agent_run_id
    questions = clarify_outcome.data.get("questions") or []
    if not clarify_outcome.data.get("needs_clarification") or not questions:
        return NodeResult(port="ok", summary=f"文案建议 → {config.output_key}（无需追问）")

    _emit(
        ctx,
        JobEventType.AWAITING_INPUT,
        JobStatus.AWAITING_INPUT,
        "文案智能体有几个问题需要你确认，请回答后继续",
        30,
        payload={"question_count": len(questions)},
    )
    return NodeResult(
        port="ok",
        suspend=True,
        checkpoint=_input_checkpoint(ctx, output_key=config.output_key, questions=questions),
        summary=f"暂停等待追问：{len(questions)} 个问题",
    )


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
        return NodeResult(
            port="retries_exhausted", summary=f"已用尽 {config.max_attempts} 次选路预算"
        )
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
    raw_cost_bias = hint.get("cost_bias")
    cost_bias = raw_cost_bias if isinstance(raw_cost_bias, (int, float)) else None
    decision = router.route(
        ctx.session,
        operation=ctx.job.operation,
        quality_tier=tier,
        max_latency_ms=config.max_latency_ms,
        exclude_providers=tried_providers,
        job_id=ctx.agent_job_id,
        user_id=ctx.job.user_id,
        selector_agent_id=config.selector_agent_id,
        request_params=ctx.params,
        cost_bias=cost_bias,
    )
    ctx.job.routing_trace_json = decision.trace()
    ctx.session.flush()

    if decision.selected is None or decision.capability is None:
        ctx.state["failure_code"] = "PROVIDER_TEMPORARY_FAILURE"
        ctx.state["failure_message"] = "暂时没有可用的生成路线，积分已退回。"
        return NodeResult(port="no_candidate", summary=f"无可用候选：{decision.reason}")

    ctx.state["decision"] = decision
    if decision.agent_run_id:
        ctx.state["_last_agent_run_id"] = decision.agent_run_id
    capability = decision.capability
    ctx.job.selected_route_summary_json = {
        "provider": capability.name,
        "provider_kind": capability.kind.value,
        "model_or_workflow": capability.model_or_workflow,
        "reason": decision.reason,
    }
    ctx.session.flush()
    return NodeResult(
        port="ok",
        summary=f"第 {attempts} 次选路 → {capability.name} / {capability.model_or_workflow}",
    )


def _attempt_status(result: GenerationResult) -> ProviderAttemptStatus:
    if result.pending:
        return ProviderAttemptStatus.RUNNING
    return ProviderAttemptStatus.SUCCEEDED if result.succeeded else ProviderAttemptStatus.FAILED


def _provider_checkpoint(
    ctx: WorkflowContext,
    *,
    capability_name: str,
    external_task_id: str,
    request: GenerationRequest,
    attempt_id: str,
) -> dict[str, object]:
    """The slice of `ctx.state` a resumed run cannot rebuild for itself.

    Only JSON-safe primitives: this is written to a database column, and the
    live `RoutingDecision` / `ProviderCapability` objects in `ctx.state` are
    rebuilt from `capability_name` against the catalogue at resume time
    instead of being serialised.
    """
    return {
        "kind": "provider",
        "capability_name": capability_name,
        "external_task_id": external_task_id,
        "provider_attempt_id": attempt_id,
        "request": asdict(request),
        "state": {
            "attempt_number": ctx.state.get("attempt_number", 1),
            "route_attempts": ctx.state.get("route_attempts", 1),
            "tried_providers": sorted(ctx.state.get("tried_providers") or ()),
            "intent_hint": ctx.state.get("intent_hint") or {},
        },
    }


def _clarify_answer_text(plan: dict[str, Any]) -> str:
    """Renders the planner's follow-up answers into a short prose fragment.

    `clarify_questions` (what was asked) and `clarify_answers` (the author's
    replies, keyed by question id — written by `POST
    /v1/generation-jobs/{id}/answer`) are both restored from the same
    checkpoint `execute_planning` wrote, so this only ever produces text after
    a real round trip; it never fabricates something the author never
    confirmed.
    """
    answers = plan.get("clarify_answers")
    questions = plan.get("clarify_questions")
    if not isinstance(answers, dict) or not answers or not isinstance(questions, list):
        return ""
    labels_by_question: dict[str, dict[str, str]] = {
        str(question.get("id")): {
            str(option.get("value")): str(option.get("label"))
            for option in (question.get("options") or [])
            if isinstance(option, dict)
        }
        for question in questions
        if isinstance(question, dict)
    }
    parts: list[str] = []
    for question_id, value in answers.items():
        labels = labels_by_question.get(question_id, {})
        if isinstance(value, list):
            parts.extend(labels.get(str(item), str(item)) for item in value if item)
        elif value:
            parts.append(labels.get(str(value), str(value)))
    return "，".join(part for part in parts if part)


def _plan_enhancements(ctx: WorkflowContext) -> tuple[str, str | None]:
    """Folds the planning node's suggestions into what actually gets sent.

    Reads the `PLAN_STATE_KEY` convention key regardless of what
    `PlanningConfig.output_key` a graph configured for the `planning` node —
    a custom graph that renamed it loses this wiring gracefully (no
    enhancement, no error). `prompt_enhancements` and `negative_prompt_
    suggestions` never overwrite the author's own text, only extend it.
    """
    plan = ctx.state.get(PLAN_STATE_KEY)
    if not isinstance(plan, dict):
        return ctx.prompt, ctx.params.get("negative_prompt")

    prompt_parts = [ctx.prompt]
    enhancements = plan.get("prompt_enhancements")
    if isinstance(enhancements, list):
        prompt_parts.extend(str(item) for item in enhancements if item)
    answer_text = _clarify_answer_text(plan)
    if answer_text:
        prompt_parts.append(answer_text)
    prompt = "，".join(part for part in prompt_parts if part)

    negative_prompt = ctx.params.get("negative_prompt")
    suggestions = plan.get("negative_prompt_suggestions")
    if isinstance(suggestions, list):
        joined = "，".join(str(item) for item in suggestions if item)
        if joined:
            negative_prompt = f"{negative_prompt}，{joined}" if negative_prompt else joined

    return prompt, negative_prompt


def _stub_generation_result(operation: str) -> GenerationResult:
    """A settled fake artifact whose mime matches the operation.

    Quality and the sandbox dialog both inspect mime type; a video dry-run
    that claims to have produced `image/png` looks like a broken provider.
    """
    if operation == Operation.AUDIO_GENERATION.value:
        return GenerationResult(
            succeeded=True,
            object_key="dry-run/stub.mp3",
            mime_type="audio/mpeg",
            duration_ms=1000,
            metadata={"dry_run": True},
        )
    if operation in _VIDEO_OPERATIONS:
        return GenerationResult(
            succeeded=True,
            object_key="dry-run/stub.mp4",
            mime_type="video/mp4",
            width=1024,
            height=576,
            duration_ms=4000,
            metadata={"dry_run": True},
        )
    return GenerationResult(
        succeeded=True,
        object_key="dry-run/stub.png",
        mime_type="image/png",
        width=1024,
        height=576,
        duration_ms=0,
        metadata={"dry_run": True},
    )


def _preview_url_for(object_key: str) -> str:
    return s3.presign_get(object_key, expires_in=get_settings().download_url_ttl_seconds)


def _sandbox_live_generate(ctx: WorkflowContext, decision: Any) -> GenerationResult:
    """Calls the selected provider without writing job/attempt/ledger rows.

    Video providers return `pending` and normally suspend for Beat. A sandbox
    request has no Beat, so this polls in-process up to the endpoint's
    `timeout_ms` (capped) and never sets `suspend`.
    """
    provider: GenerationProvider | None = decision.provider
    if provider is None:
        return GenerationResult(
            succeeded=False,
            failure_code="PROVIDER_TEMPORARY_FAILURE",
            metadata={"detail": "no provider factory for the selected route"},
        )

    operation = ctx.job.operation
    duration = int(ctx.params.get("duration_seconds") or 0)
    if operation in _VIDEO_OPERATIONS and duration < 4:
        duration = 4

    references = media_service.provider_references_for(
        ctx.session,
        user_id=ctx.job.user_id,
        asset_ids=ctx.params.get("reference_asset_ids") or [],
        video_options=ctx.params.get("video_options"),
    )
    if operation in _REFERENCE_REQUIRED and not references:
        return GenerationResult(
            succeeded=False,
            failure_code="MISSING_REFERENCE",
            metadata={"detail": "reference_asset_ids is required for this operation"},
        )

    effective_prompt, effective_negative_prompt = _plan_enhancements(ctx)
    request = GenerationRequest(
        job_id=ctx.job.id,
        operation=operation,
        quality_tier=ctx.job.quality_tier,
        prompt=effective_prompt,
        negative_prompt=effective_negative_prompt,
        seed=ctx.params.get("seed"),
        aspect_ratio=str(ctx.params.get("aspect_ratio") or "16:9"),
        duration_seconds=duration,
        references=references,
        extra=dict(ctx.params.get("extra") or {}),
    )
    result = provider.submit(request)
    if result.pending and result.external_task_id:
        timeout_ms = _sandbox_poll_budget_ms(provider, decision)
        result = _poll_sandbox_pending(provider, request, result.external_task_id, timeout_ms)
    return result


def _sandbox_poll_budget_ms(provider: GenerationProvider, decision: Any) -> int:
    """Cap in-request video polling at the endpoint timeout, then 120s.

    `typical_latency_ms` is only a fallback for test doubles that are not
    bound to a configured endpoint.
    """
    creds = getattr(provider, "_creds", None)
    endpoint_ms = int(float(getattr(creds, "timeout_s", 0) or 0) * 1000)
    typical = int(getattr(decision.capability, "typical_latency_ms", 90_000) or 90_000)
    return min(endpoint_ms or typical, _SANDBOX_POLL_CAP_MS)


def _poll_sandbox_pending(
    provider: GenerationProvider,
    request: GenerationRequest,
    external_task_id: str,
    timeout_ms: int,
) -> GenerationResult:
    deadline = time.monotonic() + timeout_ms / 1000
    last = GenerationResult(
        succeeded=False,
        pending=True,
        external_task_id=external_task_id,
        failure_code="PROVIDER_TIMEOUT",
        metadata={"detail": "sandbox poll timed out before the provider finished"},
    )
    while time.monotonic() < deadline:
        last = provider.poll(external_task_id, request)
        if not last.pending:
            return last
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(_SANDBOX_POLL_INTERVAL_SECONDS, remaining))
    if last.pending:
        return GenerationResult(
            succeeded=False,
            external_task_id=external_task_id,
            failure_code="PROVIDER_TIMEOUT",
            metadata={"detail": "sandbox poll timed out before the provider finished"},
        )
    return last


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
        if ctx.live_provider:
            result = _sandbox_live_generate(ctx, decision)
        else:
            result = _stub_generation_result(ctx.job.operation)
    else:
        # A retry re-enters with the job already `running`; the state
        # machine rightly refuses running -> running.
        if ctx.job.status == JobStatus.QUEUED:
            ctx.job = sm.transition(ctx.session, ctx.job.id, JobStatus.SUBMITTED)
        effective_prompt, effective_negative_prompt = _plan_enhancements(ctx)
        _emit(
            ctx,
            JobEventType.GENERATING,
            JobStatus.SUBMITTED,
            "正在生成",
            40,
            payload={
                "prompt": effective_prompt,
                "negative_prompt": effective_negative_prompt,
            },
        )
        if ctx.job.status != JobStatus.RUNNING:
            ctx.job = sm.transition(ctx.session, ctx.job.id, JobStatus.RUNNING)

        ctx.session.refresh(ctx.job)
        if ctx.job.cancel_requested_at is not None:
            ctx.job = honor_user_cancel(ctx.session, ctx.job)
            return NodeResult(
                port="cancelled", terminal=PipelineOutcome(status=JobStatus.CANCELLED)
            )

        request = GenerationRequest(
            job_id=ctx.job.id,
            operation=ctx.job.operation,
            quality_tier=ctx.job.quality_tier,
            prompt=effective_prompt,
            negative_prompt=effective_negative_prompt,
            seed=ctx.params.get("seed"),
            aspect_ratio=str(ctx.params.get("aspect_ratio") or "16:9"),
            duration_seconds=int(ctx.params.get("duration_seconds") or 0),
            references=media_service.provider_references_for(
                ctx.session,
                user_id=ctx.job.user_id,
                asset_ids=ctx.params.get("reference_asset_ids") or [],
                video_options=ctx.params.get("video_options"),
            ),
            extra=dict(ctx.params.get("extra") or {}),
        )
        result = decision.provider.submit(request)
        attempt = ProviderAttempt(
            job_id=ctx.job.id,
            provider=capability.name,
            provider_kind=capability.kind,
            model_or_workflow_version=capability.model_or_workflow,
            external_task_id=result.external_task_id,
            attempt_number=attempt_number,
            status=_attempt_status(result),
            cost_minor=result.cost_minor,
            latency_ms=result.latency_ms,
            failure_code=result.failure_code,
            raw_metadata_redacted_json=result.metadata,
            created_at=utcnow(),
        )
        ctx.session.add(attempt)
        ctx.session.flush()

        ctx.session.refresh(ctx.job)
        if ctx.job.cancel_requested_at is not None:
            if result.pending and result.external_task_id:
                try:
                    decision.provider.cancel(result.external_task_id)
                except Exception:
                    logger.exception(
                        "provider.cancel failed after submit for job %s", ctx.job.id
                    )
            attempt.status = ProviderAttemptStatus.CANCELLED
            ctx.session.flush()
            ctx.job = honor_user_cancel(ctx.session, ctx.job)
            return NodeResult(
                port="cancelled", terminal=PipelineOutcome(status=JobStatus.CANCELLED)
            )

        if result.pending and result.external_task_id:
            # The upstream owns the work now. Suspending keeps the job
            # `RUNNING` with no Celery task in flight — see
            # `app.models.async_tasks` — and the statistics stay unrecorded
            # until the outcome is actually known.
            _emit(
                ctx,
                JobEventType.GENERATING,
                JobStatus.RUNNING,
                "已提交生成任务，正在渲染",
                45,
                payload={
                    "external_task_id": result.external_task_id,
                    "prompt": effective_prompt,
                    "negative_prompt": effective_negative_prompt,
                },
            )
            return NodeResult(
                port="succeeded",
                suspend=True,
                checkpoint=_provider_checkpoint(
                    ctx,
                    capability_name=capability.name,
                    external_task_id=result.external_task_id,
                    request=request,
                    attempt_id=attempt.id,
                ),
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
        detail = result.metadata.get("detail") if isinstance(result.metadata, dict) else None
        if detail:
            ctx.state["error_detail"] = str(detail)
        _emit(
            ctx,
            JobEventType.PROGRESS,
            JobStatus.RUNNING,
            "这条线路暂时不可用，正在尝试其他路线",
            45,
            internal_code=ctx.state["failure_code"],
        )
        failure_summary = f"{capability.name} 失败：{ctx.state['failure_code']}"
        skip_retry = (
            (ctx.dry_run and ctx.live_provider)
            or result.failure_code in {"MISSING_REFERENCE", "PROVIDER_TIMEOUT"}
            or not config.retry_on_failure
        )
        if skip_retry:
            # `error_detail` is admin-sandbox only; C-end `failure_message`
            # must stay a public sentence (no HTTP bodies / timeouts).
            ctx.state["failure_message"] = "生成失败，积分已退回。"
            return NodeResult(port="failed", summary=failure_summary)
        return NodeResult(port="retry", summary=failure_summary)

    ctx.state["result"] = result
    ctx.state["capability"] = capability
    if ctx.dry_run and ctx.live_provider and result.object_key:
        ctx.state["_preview_url"] = _preview_url_for(result.object_key)
        ctx.state["_preview_mime_type"] = result.mime_type
    return NodeResult(port="succeeded", summary=f"{capability.name} 第 {attempt_number} 次尝试成功")


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
            "partial_output": bool(result and result.metadata.get("partial_output")),
            "upstream_status": result.metadata.get("upstream_status") if result else None,
        },
        attempt_number=attempt_number,
        job_id=ctx.agent_job_id,
        user_id=ctx.job.user_id,
        agent_id=config.agent_id,
    )
    ctx.state["_last_agent_run_id"] = outcome.agent_run_id

    if outcome.data.get("verdict") == "fail":
        ctx.state["failure_code"] = "QUALITY_REJECTED"
        if outcome.data.get("should_retry") and not (ctx.dry_run and ctx.live_provider):
            _emit(
                ctx,
                JobEventType.PROGRESS,
                JobStatus.RUNNING,
                "输出质量不理想，正在重新生成",
                50,
                internal_code="QUALITY_REJECTED",
            )
            return NodeResult(port="retry", summary="不达标，建议重试")
        ctx.state["failure_message"] = "生成结果未通过质量校验，积分已退回。"
        return NodeResult(port="fail", summary="不达标，不再重试")

    if ctx.dry_run or result is None or capability is None:
        ctx.state["asset_id"] = None
        ctx.state["actual_credits"] = 0
        return NodeResult(port="pass", summary="达标（沙盒未登记产出）")

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
    if ctx.is_sandbox:
        # Product sandbox is a real job; successful output still needs a
        # human look in the moderation queue even though Safety already
        # passed. C-end jobs do not take this path.
        moderation_queue.enqueue_for_review(
            ctx.session,
            subject_type="generation_job",
            subject_id=ctx.job.id,
            stage=ModerationStage.POST_GENERATION,
            reason_code="SANDBOX_OUTPUT",
        )
    return NodeResult(port="pass", summary=f"达标，结算 {ctx.state['actual_credits']} 积分")


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
