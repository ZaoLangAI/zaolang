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
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import asdict
from typing import Any

from app.agents import copywriter, planner, quality, router, safety
from app.agents import custom as custom_agent
from app.agents import intent_router as intent_router_agent
from app.config import get_settings
from app.domain.characters import service as characters_service
from app.domain.costs import service as costs_service
from app.domain.credits.pricing import settlement_credits
from app.domain.errors import NotFound, ValidationFailed
from app.domain.image_assets import prompt_builder
from app.domain.image_assets.vocabulary import (
    EXPRESSION_PRESETS,
    scene_preset_label,
    scene_presets_from,
)
from app.domain.jobs import service as jobs_service
from app.domain.jobs import state_machine as sm
from app.domain.jobs.cancellation import honor_user_cancel
from app.domain.media import reference_roles
from app.domain.media import service as media_service
from app.domain.moderation_queue import service as moderation_queue
from app.domain.scenes import service as scenes_service
from app.domain.skill_library import service as skill_library_service
from app.domain.skill_library.folding import (
    flat_template_params,
    fold_params_prompt,
    foldable_params,
)
from app.domain.style_gallery import service as style_gallery_service
from app.llm import client as llm_client
from app.llm.client import StreamChunk
from app.models import Draft, GenerationJob, JobEvent, ProviderAttempt
from app.models.base import utcnow
from app.models.enums import (
    IMAGE_ASSET_SKILL_CATEGORIES,
    CharacterViewAngle,
    ImageAssetKind,
    JobEventType,
    JobStatus,
    ModerationStage,
    ModerationStatus,
    Operation,
    ProviderAttemptStatus,
    QualityTier,
    VideoAssetKind,
)
from app.providers.base import (
    AdaptedResolution,
    GenerationProvider,
    GenerationRequest,
    GenerationResult,
    adapt_resolution_tier,
)
from app.realtime import publisher
from app.storage import s3
from app.workflows.configs import (
    AssetOutputAdvanceConfig,
    AssetOutputLinkConfig,
    AssetPlanningConfig,
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
    VideoAnalysisGenerateConfig,
)
from app.workflows.types import (
    DEFERRED_JOB_EVENT_STATE_KEY,
    NodeResult,
    PipelineOutcome,
    WorkflowContext,
)

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
        # `image_to_image` deliberately excluded: the prompt is what's
        # mandatory, a reference image is only optional extra context that
        # rides along with it (see `workflow_templates_service
        # .canonical_operation`) — unlike video reference/first-frame input,
        # which the provider genuinely cannot proceed without.
        Operation.IMAGE_TO_VIDEO.value,
        Operation.VIDEO_TO_VIDEO.value,
        # There is nothing to analyze without the source clip — unlike every
        # generation operation above, `prompt` here is the optional part
        # (a supplementary note), so this is the one thing standing in for
        # "the request has an actual subject".
        Operation.VIDEO_ANALYSIS.value,
    }
)
_SANDBOX_POLL_INTERVAL_SECONDS = 2.0
_SANDBOX_POLL_CAP_MS = 120_000


def _requested_resolution(params: Mapping[str, Any]) -> str | None:
    video_options = params.get("video_options") or {}
    if not isinstance(video_options, Mapping):
        return None
    raw = video_options.get("resolution")
    return str(raw) if raw else None


def _adapted_generation_resolution(
    capability: Any, params: Mapping[str, Any]
) -> AdaptedResolution | None:
    requested = _requested_resolution(params)
    if not requested:
        return None
    available = capability.resolutions if capability is not None else None
    return adapt_resolution_tier(requested, available)


def _vendor_resolution_for(capability: Any, params: Mapping[str, Any]) -> str | None:
    adapted = _adapted_generation_resolution(capability, params)
    return adapted.vendor_literal if adapted is not None else None


def _resolution_adapt_fields(capability: Any, params: Mapping[str, Any]) -> dict[str, str]:
    """Ops-replay fields. User-facing copy must use `adapted_resolution`
    (studio tier), never `adapted_vendor_resolution` (`768P`)."""

    requested = _requested_resolution(params)
    if not requested:
        return {}
    adapted = _adapted_generation_resolution(capability, params)
    fields: dict[str, str] = {"requested_resolution": requested}
    if adapted is not None:
        fields["adapted_resolution"] = adapted.studio_tier
        fields["adapted_vendor_resolution"] = adapted.vendor_literal
        fields["resolution_adapt_kind"] = adapted.kind
    return fields


def _event_frame(event: JobEvent) -> dict[str, object]:
    return {
        "sequence": event.sequence,
        "event_type": event.event_type,
        "status": event.status,
        "progress": event.progress,
        "message": event.public_message,
        "node_id": event.node_id,
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
    publish: bool = True,
) -> None:
    """Writes a real `JobEvent` and, by default, publishes it.

    A no-op when `ctx.dry_run` is set: unit tests walk a graph without a
    persisted job, so there is no event stream to attach one to.

    `publish=False` only appends the row (no commit, no Redis). The
    `AWAITING_INPUT` path uses this so `WorkflowRunner._suspend` can commit
    the event together with the `WorkflowInputRequest` row and the status
    transition, then publish — otherwise the C-end mounts the question
    panel on the SSE frame and GETs `/input-request` before the row exists.
    """
    scaled = _scale_for_character_views(ctx, progress)
    ctx.state["_last_event_status"] = status.value
    ctx.state["_last_event_progress"] = scaled
    if ctx.dry_run:
        return
    event = sm.append_event(
        ctx.session,
        ctx.job.id,
        event_type=event_type,
        status=status,
        public_message=message,
        progress=scaled,
        internal_code=internal_code,
        payload=payload,
        node_id=ctx.state.get("_current_node_id"),
    )
    frame = _event_frame(event)
    if not publish:
        ctx.state[DEFERRED_JOB_EVENT_STATE_KEY] = frame
        return
    ctx.session.commit()
    publisher.publish_job_event(ctx.job.id, frame)


def publish_thinking(ctx: WorkflowContext, text: str) -> None:
    """Live Redis thinking frame — not a `JobEvent` row, no `sequence`."""
    if ctx.dry_run or not text:
        return
    publisher.publish_job_event(
        ctx.job.id,
        {
            "event_type": "thinking",
            "node_id": ctx.state.get("_current_node_id"),
            "status": ctx.state.get("_last_event_status") or ctx.job.status,
            "progress": ctx.state.get("_last_event_progress") or 0,
            "message": "",
            "thinking": text,
        },
    )


@contextmanager
def _live_thinking(ctx: WorkflowContext) -> Iterator[None]:
    def on_chunk(chunk: StreamChunk) -> None:
        if chunk.kind == "thinking" and chunk.text:
            publish_thinking(ctx, chunk.text)

    with llm_client.bind_on_chunk(on_chunk):
        yield


def execute_safety_check(ctx: WorkflowContext, config: SafetyCheckConfig) -> NodeResult:
    _emit(ctx, JobEventType.SAFETY, JobStatus.QUEUED, "正在进行安全检查", 8)
    with _live_thinking(ctx):
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
    `fold_params_prompt`).

    Order: the style gallery entry first (one, mutually exclusive), then
    `skill_ids` in pick order. Later templates win on conflicting keys;
    the user's own explicit params (non-`None`) always win over every
    template. A skill whose `applicable_operations` doesn't include this
    job's operation is skipped, same as an unusable/missing skill or style.

    A skill whose category is in `IMAGE_ASSET_SKILL_CATEGORIES` (character/
    scene_asset/cover_asset) only folds its *flat* recipe keys (`prompt` /
    `prompt_suffix` / `aspect_ratio` / `negative_prompt`) — the nested
    `character`/`scene` bundles stay out of `ctx.params` so they cannot
    leak `reference_assets` into the provider request. A user-authored
    roster skill with no flat keys is still skipped, same as before. A
    character/scene used as a *cast member* still goes through
    `character_ids`/`scene_ids`/`target_*_id` and
    `characters_service.apply_character_refs` /
    `scenes_service.apply_scene_refs` (called by `jobs.service.submit`
    before this node ever runs).
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
            ctx.prompt = fold_params_prompt(ctx.prompt, entry.params_json)
            template_params.update(entry.params_json)

    for skill_id in skill_ids:
        try:
            skill = skill_library_service.get_usable(
                ctx.session, skill_id=str(skill_id), viewer_id=ctx.job.user_id
            )
            if not skill_library_service.viewer_has_access(ctx.session, skill, ctx.job.user_id):
                raise NotFound("技能未解锁。")
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
        if skill.category in IMAGE_ASSET_SKILL_CATEGORIES:
            fold = flat_template_params(skill.params_json)
            if not fold:
                continue
            ctx.prompt = fold_params_prompt(ctx.prompt, fold)
            template_params.update(fold)
            continue
        # `foldable_params`, not the raw bag: a workflow skill's `variables`
        # are the questions asked *before* the run, and folding them here
        # would hand the provider the form instead of the answers.
        fold = foldable_params(skill.params_json)
        ctx.prompt = fold_params_prompt(ctx.prompt, fold)
        template_params.update(fold)

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


def _has_reference_material(ctx: WorkflowContext) -> bool:
    """True once this job carries a reference image/video — a remix's source
    clip (`media_service.attach_licensed_source_video` prepends it into
    `reference_asset_ids`) or an `image_to_video` first/last frame. The
    `clarify` sub-step below must not ask "who/what is the subject" or
    "what is the background/scene" once one of these is present — the
    reference material already answers that, not the intent text.
    """
    if ctx.params.get("reference_asset_ids"):
        return True
    video_options = ctx.params.get("video_options") or {}
    return bool(
        video_options.get("first_frame_asset_id") or video_options.get("last_frame_asset_id")
    )


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
    with _live_thinking(ctx):
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

    with _live_thinking(ctx):
        clarify_outcome = planner.clarify(
            ctx.session,
            intent=ctx.prompt,
            has_reference_material=_has_reference_material(ctx),
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
        publish=False,
    )
    return NodeResult(
        port="ok",
        suspend=True,
        checkpoint=_input_checkpoint(ctx, output_key=config.output_key, questions=questions),
        summary=f"暂停等待追问：{len(questions)} 个问题",
    )


def execute_intent_router(ctx: WorkflowContext, config: IntentRouterConfig) -> NodeResult:
    _emit(ctx, JobEventType.INTENT_ROUTING, JobStatus.QUEUED, "正在理解生成意图", 20)
    with _live_thinking(ctx):
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


ASSET_PLAN_STATE_KEY = "asset_plan"
ASSET_OUTPUTS_STATE_KEY = "asset_outputs"
# One write-back label per image of a scene variant group, in variant order
# (`prompt_builder.group_labels`).
GROUP_LABELS_STATE_KEY = "group_labels"
# Every image a scene variant group delivered, `{asset_id, label}` in order
# (`_register_group_outputs`); `asset_output_advance` records them all.
GROUP_OUTPUTS_STATE_KEY = "group_outputs"
_ORIGINAL_PROMPT_STATE_KEY = "_asset_plan_original_prompt"
_ORIGINAL_NEGATIVE_PROMPT_STATE_KEY = "_asset_plan_original_negative_prompt"

# The fixed character/scene prompt fragments live in
# `app.domain.image_assets.prompt_builder` now; these aliases keep the names
# older callers and tests import from here.
_CHARACTER_COMPLETION_FIXED_PROMPTS = prompt_builder.CHARACTER_COMPLETION_FIXED_PROMPTS
_CHARACTER_COMPLETION_FIXED_NEGATIVE_PROMPT = (
    prompt_builder.CHARACTER_COMPLETION_FIXED_NEGATIVE_PROMPT
)
_CHARACTER_SHEET_LAYOUT_SUFFIX = prompt_builder.CHARACTER_SHEET_LAYOUT_SUFFIX
_CHARACTER_PHOTOREAL_MEDIUM = prompt_builder.CHARACTER_PHOTOREAL_MEDIUM
_CHARACTER_PHOTOREAL_NEGATIVE = prompt_builder.CHARACTER_PHOTOREAL_NEGATIVE
_CHARACTER_ANIME_NEGATIVE = prompt_builder.CHARACTER_ANIME_NEGATIVE
_merge_negative = prompt_builder.merge_negative


def _apply_character_visual_medium(ctx: WorkflowContext) -> None:
    """Locks a character pass to one visual medium — see
    `prompt_builder.apply_visual_medium`."""
    ctx.prompt, ctx.params["negative_prompt"] = prompt_builder.apply_visual_medium(
        ctx.prompt, ctx.params.get("negative_prompt")
    )


def _current_character_view(ctx: WorkflowContext) -> str:
    """Which view a `CHARACTER`-kind job's current loop iteration targets.

    Before `execute_asset_output_advance` ever runs (the job's first pass),
    this is the first entry of `character_views` (defaulting to `front` for
    a plain single-view job — see `GenerationParams.character_views`); once
    it has run, the advance node has already stashed the next view under
    `_current_character_view`, which takes priority here.
    """
    stashed = ctx.state.get("_current_character_view")
    if stashed:
        return str(stashed)
    views = ctx.params.get("character_views")
    if isinstance(views, list) and views:
        return str(views[0])
    return CharacterViewAngle.FRONT.value


def _start_next_asset_pass(ctx: WorkflowContext) -> None:
    """Gives a multi-view job's next pass a fresh routing budget.

    Each view is its own generation: the previous view already succeeded,
    so neither its spent `route_attempts` nor the providers it excluded
    along the way (`tried_providers`, plus the stale `failure_code` that
    `execute_route_score` reads to grow that set) say anything about this
    one. `attempt_seq` is deliberately *not* reset — it keeps numbering
    output object keys uniquely across the whole job.
    """
    ctx.state["route_attempts"] = 0
    ctx.state["tried_providers"] = set()
    ctx.state.pop("failure_code", None)
    ctx.state.pop("decision", None)


def _scale_for_character_views(ctx: WorkflowContext, progress: int) -> int:
    """Rescales a node's fixed progress constant for a multi-view `CHARACTER`
    job, so the overall bar climbs once per produced view instead of
    restarting from the same per-node constant on every loop-back through
    `asset_planning` (see `execute_asset_output_advance`).

    A no-op for every job that isn't `asset_kind=CHARACTER` with more than
    one `character_views` entry — every other job's progress numbers are
    unchanged. Safe to apply to *every* emitted event unconditionally
    (including `queued`/`safety`, which only ever fire once before the loop
    even starts, and the terminal `succeeded`/`failed` events, whose raw
    stored value doesn't matter since `progress_for` and the frontend both
    already force 100 for a terminal status regardless of what's stored).
    """
    if ctx.params.get("asset_kind") != ImageAssetKind.CHARACTER.value:
        return progress
    raw_views = ctx.params.get("character_views")
    views = [str(v) for v in raw_views] if isinstance(raw_views, list) and raw_views else []
    if len(views) <= 1:
        return progress
    try:
        view_index = views.index(_current_character_view(ctx))
    except ValueError:
        view_index = 0
    return round((view_index * 100 + progress) / len(views))


def _asset_axis(ctx: WorkflowContext) -> tuple[str, str] | None:
    """Which of the two orthogonal asset-kind axes is active on this job.

    Returns `("image", kind_value)` / `("video", kind_value)`, or `None` for
    a plain `GENERAL`/unset job on both axes. `validate_generation_params`
    (`app.api.schemas.jobs`) already guarantees at most one axis is
    non-`GENERAL` at a time (image kinds are rejected outside
    `IMAGE_OPERATIONS`, video kinds outside `VIDEO_OPERATIONS`), so checking
    `asset_kind` first and falling back to `video_asset_kind` is safe — a
    video job's `asset_kind` always still sits at its `GENERAL` default.
    """
    image_kind = ctx.params.get("asset_kind")
    if image_kind and image_kind != ImageAssetKind.GENERAL.value:
        return "image", str(image_kind)
    video_kind = ctx.params.get("video_asset_kind")
    if video_kind and video_kind != VideoAssetKind.GENERAL.value:
        return "video", str(video_kind)
    return None


def execute_asset_planning(ctx: WorkflowContext, config: AssetPlanningConfig) -> NodeResult:
    """Runs the planner agent's `asset_plan` slot for a character/scene/cover
    image job — or its video-side equivalent for a scene/character-action/
    transition/cover *video* job — folding its guidance into `ctx.prompt`.

    A no-op when neither asset-kind axis is set or both are `GENERAL` — see
    `AssetPlanningConfig`. Re-entered once per remaining `character_views`
    entry (via `execute_asset_output_advance`'s loop-back edge) for a
    multi-view `CHARACTER` *image* job only — no video kind ever loops (see
    `_asset_axis`) — `ctx.prompt` is reset to the request's original prompt
    on every entry first, so the second/third pass enhances that, not
    whatever the previous view's pass already appended to it.

    The reset prompt is then composed by `prompt_builder.compose` for this
    pass (`prompt_builder.resolve_pass`): a side/back completion is
    hard-overridden by a fixed reference-driven instruction; a sheet keeps
    the caller's identity text, gains the sheet layout (and a 换装 prefix
    for a named outfit with a reference) plus the medium lock; a composite
    expression image gets the grid layout instead of the sheet; a scene
    gets its lighting/weather/state/period fragments (prefixed by the
    master-plate lock when a reference exists) or, for a variant group,
    one line per image. `ctx.params["negative_prompt"]` gets the same
    reset-then-compose treatment (via `_ORIGINAL_NEGATIVE_PROMPT_STATE_KEY`)
    so a later pass never inherits the previous one's text. The planner's
    additions are filtered by `prompt_builder.sanitize_enhancements`.
    """
    axis = _asset_axis(ctx)
    if axis is None:
        return NodeResult(port="ok")
    media_axis, asset_kind = axis

    if ctx.state.get(ASSET_OUTPUTS_STATE_KEY):
        _start_next_asset_pass(ctx)

    if _ORIGINAL_PROMPT_STATE_KEY not in ctx.state:
        ctx.state[_ORIGINAL_PROMPT_STATE_KEY] = ctx.prompt
    ctx.prompt = ctx.state[_ORIGINAL_PROMPT_STATE_KEY]
    if _ORIGINAL_NEGATIVE_PROMPT_STATE_KEY not in ctx.state:
        ctx.state[_ORIGINAL_NEGATIVE_PROMPT_STATE_KEY] = ctx.params.get("negative_prompt")
    ctx.params["negative_prompt"] = ctx.state[_ORIGINAL_NEGATIVE_PROMPT_STATE_KEY]

    is_character = media_axis == "image" and asset_kind == ImageAssetKind.CHARACTER.value
    character_view = _current_character_view(ctx) if is_character else None
    asset_pass = (
        prompt_builder.resolve_pass(
            ctx.params, asset_kind=asset_kind, character_view=character_view
        )
        if media_axis == "image"
        else prompt_builder.AssetPass.OTHER
    )
    ctx.prompt, ctx.params["negative_prompt"] = prompt_builder.compose(
        asset_pass,
        prompt=ctx.prompt,
        negative=ctx.params.get("negative_prompt"),
        params=ctx.params,
        character_view=character_view,
        has_reference=bool(ctx.params.get("reference_asset_ids")),
    )
    if asset_pass is prompt_builder.AssetPass.SCENE_VARIANT_GROUP:
        ctx.state[GROUP_LABELS_STATE_KEY] = prompt_builder.group_labels(ctx.params)

    if media_axis == "video":
        _emit(ctx, JobEventType.PLANNING, JobStatus.QUEUED, "正在规划视频资产生成方案", 16)
        with _live_thinking(ctx):
            outcome = planner.plan_video_asset(
                ctx.session,
                intent=ctx.prompt,
                video_asset_kind=asset_kind,
                target_character_id=ctx.params.get("target_character_id"),
                target_scene_id=ctx.params.get("target_scene_id"),
                source_params=ctx.params,
                job_id=ctx.agent_job_id,
                user_id=ctx.job.user_id,
                agent_id=config.agent_id,
            )
    else:
        _emit(ctx, JobEventType.PLANNING, JobStatus.QUEUED, "正在规划图片资产生成方案", 16)
        with _live_thinking(ctx):
            outcome = planner.plan_asset(
                ctx.session,
                intent=ctx.prompt,
                asset_kind=asset_kind,
                character_view=character_view,
                asset_pass=asset_pass.value,
                target_character_id=ctx.params.get("target_character_id"),
                target_scene_id=ctx.params.get("target_scene_id"),
                source_params=ctx.params,
                job_id=ctx.agent_job_id,
                user_id=ctx.job.user_id,
                agent_id=config.agent_id,
            )
    ctx.state[config.output_key] = outcome.data
    ctx.state["_last_agent_run_id"] = outcome.agent_run_id

    enhancements = outcome.data.get("prompt_enhancements")
    if isinstance(enhancements, list) and enhancements:
        kept = prompt_builder.sanitize_enhancements(asset_pass, enhancements, params=ctx.params)
        addition = "，".join(kept)
        if addition and addition not in ctx.prompt:
            ctx.prompt = f"{ctx.prompt}，{addition}" if ctx.prompt else addition
    negative_suggestions = outcome.data.get("negative_prompt_suggestions")
    if isinstance(negative_suggestions, list) and negative_suggestions:
        addition = "，".join(str(item) for item in negative_suggestions if item)
        existing = ctx.params.get("negative_prompt")
        if addition and addition not in (existing or ""):
            ctx.params["negative_prompt"] = _merge_negative(existing, addition)
    subject_name = outcome.data.get("subject_name")
    label = character_view or config.output_key
    return NodeResult(port="ok", summary=f"资产规划 → {subject_name or label}")


def execute_asset_output_advance(
    ctx: WorkflowContext, config: AssetOutputAdvanceConfig
) -> NodeResult:
    """Records this pass's output, then decides whether another view is due.

    Sits between `quality_check` and `asset_output_link`. A single pass for
    anything but an image `CHARACTER`-kind job — `scene`/`cover`/`general`
    (and every video kind — no video kind ever loops, see `_asset_axis`)
    take the `done` port immediately, exactly like before this node type
    existed. A `CHARACTER` job with more than one `character_views` entry
    loops back to `asset_planning` (the `next` port) once per remaining
    view; `asset_id` is unset only in a dry run with no registered output,
    in which case nothing is recorded but the loop still advances so a
    sandbox try-it walks the whole graph.
    """
    axis = _asset_axis(ctx)
    asset_kind = axis[1] if axis else None
    outputs: list[dict[str, str]] = ctx.state.setdefault(ASSET_OUTPUTS_STATE_KEY, [])
    asset_id = ctx.state.get("asset_id")
    is_character = (
        axis is not None and axis[0] == "image" and asset_kind == ImageAssetKind.CHARACTER.value
    )
    view = _current_character_view(ctx) if is_character else str(asset_kind or "")
    group_outputs = ctx.state.get(GROUP_OUTPUTS_STATE_KEY)
    if group_outputs:
        outputs.extend(
            {"asset_id": str(entry["asset_id"]), "view": view, "label": str(entry["label"])}
            for entry in group_outputs
        )
    elif asset_id:
        outputs.append({"asset_id": str(asset_id), "view": view})

    if not is_character:
        return NodeResult(port="done")

    raw_views = ctx.params.get("character_views")
    views = (
        [str(v) for v in raw_views]
        if isinstance(raw_views, list) and raw_views
        else [CharacterViewAngle.FRONT.value]
    )
    try:
        next_index = views.index(view) + 1
    except ValueError:
        next_index = len(views)
    if next_index >= len(views):
        return NodeResult(port="done")

    ctx.state["_current_character_view"] = views[next_index]
    return NodeResult(
        port="next",
        summary=f"继续生成第 {next_index + 1}/{len(views)} 张（{views[next_index]}）",
    )


def execute_asset_output_link(ctx: WorkflowContext, config: AssetOutputLinkConfig) -> NodeResult:
    """Attaches every output `execute_asset_output_advance` recorded to its
    character/scene target — one entry for a plain single-view job, one per
    produced view for a multi-view `CHARACTER` completion job (image only —
    a video job's `outputs` always has exactly one entry).

    Falls back to `ctx.state["asset_id"]` alone when nothing populated
    `asset_outputs` — a hand-edited graph may wire this node directly after
    `quality_check` without `asset_output_advance` in between, same as every
    graph did before that node type existed.

    Never fails the job: an attach problem (an unowned/deleted target, a
    full reference-asset list) is logged and skipped rather than turning a
    successful generation into a failure this late in the graph.
    """
    axis = _asset_axis(ctx)
    media_axis, asset_kind = axis if axis else (None, None)
    outputs = ctx.state.get(ASSET_OUTPUTS_STATE_KEY)
    if not outputs:
        fallback_id = ctx.state.get("asset_id")
        is_character = media_axis == "image" and asset_kind == ImageAssetKind.CHARACTER.value
        view = _current_character_view(ctx) if is_character else str(asset_kind or "")
        outputs = [{"asset_id": str(fallback_id), "view": view}] if fallback_id else []
    if ctx.dry_run or not outputs or axis is None:
        return NodeResult(port="ok")
    if ctx.params.get("auto_attach_asset") is False:
        return NodeResult(port="ok")

    plan = ctx.state.get(ASSET_PLAN_STATE_KEY) or {}
    # `subject_name_hint` (only ever sent by a caller that already knows the
    # exact name — e.g. the script studio's "生成角色图/场景图" jump-out,
    # which carries the script's own character name/scene heading) wins over
    # the planner's own guess from the prompt. The fallback text is kind-
    # specific so a scene auto-create never inherits "新角色".
    is_scene_kind = asset_kind == ImageAssetKind.SCENE.value
    default_subject_name = "新场景" if is_scene_kind else "新角色"
    subject_name = (
        str(
            ctx.params.get("subject_name_hint") or plan.get("subject_name") or default_subject_name
        ).strip()[:60]
        or default_subject_name
    )

    try:
        if media_axis == "video":
            if asset_kind == VideoAssetKind.CHARACTER_ACTION.value:
                target_id = ctx.params.get("target_character_id")
                for entry in outputs:
                    target_id = _link_character_action_output(
                        ctx,
                        config,
                        asset_id=str(entry.get("asset_id")),
                        subject_name=subject_name,
                        target_id=target_id,
                    )
                if target_id:
                    ctx.job.linked_character_id = target_id
                    ctx.session.flush()
            # `CHARACTER_ACTION` is handled above; `TRANSITION`/`COVER` video
            # have no library to attach to, same as image `COVER` below —
            # the output stays a plain generated asset.
        elif asset_kind == ImageAssetKind.CHARACTER.value:
            target_id = ctx.params.get("target_character_id")
            expressions = ctx.params.get("character_expressions")
            for entry in outputs:
                # One output failing to attach must not drop the others; the
                # savepoint keeps a failed SQL statement from poisoning the
                # job's own transaction.
                try:
                    with ctx.session.begin_nested():
                        target_id = _link_character_output(
                            ctx,
                            config,
                            asset_id=str(entry.get("asset_id")),
                            # A composite expression image is a free-form extra,
                            # never a front/side/back sheet view it could replace.
                            view=CharacterViewAngle.GENERAL.value
                            if expressions
                            else str(entry.get("view") or CharacterViewAngle.FRONT.value),
                            label=_character_output_label(ctx.params),
                            subject_name=subject_name,
                            target_id=target_id,
                        )
                except Exception:
                    logger.exception(
                        "job %s could not attach character output %s",
                        ctx.job.id,
                        entry.get("asset_id"),
                    )
            # Recorded on the job row (not just `ctx.state`) so it survives
            # into `GenerationJobResponse` — the script studio's "返回文案
            # 创作" jump-back reads this to know which card to auto-relink.
            # Flushed immediately: the session is `autoflush=False`
            # (`app.db`), and the runner's `_cancel_if_requested` calls
            # `session.refresh(ctx.job)` right after this node returns —
            # without an explicit flush that silently discards this
            # unflushed attribute, reverting it back to `None` (see
            # `execute_route_score`'s `routing_trace_json`/
            # `selected_route_summary_json` for the same pattern).
            if target_id:
                ctx.job.linked_character_id = target_id
                ctx.session.flush()
        elif asset_kind == ImageAssetKind.SCENE.value:
            target_id = ctx.params.get("target_scene_id")
            for entry in outputs:
                try:
                    with ctx.session.begin_nested():
                        target_id = _link_scene_output(
                            ctx,
                            config,
                            asset_id=str(entry.get("asset_id")),
                            view=str(entry.get("view") or ""),
                            label=_scene_output_label(ctx.params, entry),
                            subject_name=subject_name,
                            target_id=target_id,
                        )
                except Exception:
                    logger.exception(
                        "job %s could not attach scene output %s", ctx.job.id, entry.get("asset_id")
                    )
            if target_id:
                ctx.job.linked_scene_id = target_id
                ctx.session.flush()
        # `COVER` has no library to attach to today — the output stays a
        # plain generated asset (see the plan's "补充功能建议" for a future
        # series/episode cover slot).
    except Exception:
        logger.exception(
            "job %s asset_output_link failed for media_axis=%s asset_kind=%s",
            ctx.job.id,
            media_axis,
            asset_kind,
        )
    return NodeResult(port="ok")


def _character_output_label(params: dict[str, Any]) -> str | None:
    """The reference-entry label a character output is filed under: the
    outfit name for a sheet, or `表情·冷笑/隐忍…` for a composite expression
    image (≤60, the label column's own limit)."""
    expressions = params.get("character_expressions")
    if isinstance(expressions, list) and expressions:
        names = [
            EXPRESSION_PRESETS[str(key)].label
            for key in expressions
            if str(key) in EXPRESSION_PRESETS
        ]
        return f"表情·{'/'.join(names)}"[:60] if names else "表情"
    outfit = params.get("character_outfit_label")
    return str(outfit).strip()[:60] or None if isinstance(outfit, str) else None


def _scene_output_label(params: dict[str, Any], entry: dict[str, Any]) -> str | None:
    """A scene output's label: its own variant label (a variant group sets
    one per image), else the single-image presets' combined label."""
    own = entry.get("label")
    if isinstance(own, str) and own.strip():
        return own.strip()[:60]
    return scene_preset_label(scene_presets_from(params))[:60] or None


def _link_character_output(
    ctx: WorkflowContext,
    config: AssetOutputLinkConfig,
    *,
    asset_id: str,
    view: str,
    subject_name: str,
    target_id: str | None,
    label: str | None = None,
) -> str | None:
    """Attaches one output to `target_id`, auto-creating a character from
    scratch on the first call if there was none — also the fallback when
    `target_id` no longer resolves (e.g. the script studio's cached
    `character_ref_id` outlived the character it pointed at, which a
    delete leaves dangling rather than cleaning up). A same-name card the
    owner already has is reused instead of creating a second one
    (`characters.service` titles are unique per owner).

    Returns the id actually used (whichever was passed in, the one just
    created, or a fresh replacement for a stale target) —
    `execute_asset_output_link` threads it through the loop over `outputs`
    so a multi-view completion job's later views land on the exact same
    character its first view did, rather than each auto-creating its own.
    """
    if target_id:
        try:
            characters_service.append_reference_asset(
                ctx.session,
                user_id=ctx.job.user_id,
                character_id=str(target_id),
                asset_id=asset_id,
                view=view,
                label=label,
            )
            return target_id
        except NotFound:
            # `target_id` was deleted (or never belonged to this user)
            # since whoever sent it last saw it — fall through to the
            # auto-create branch below instead of losing this output.
            logger.warning(
                "job %s target_character_id=%s no longer exists; auto-creating a replacement",
                ctx.job.id,
                target_id,
            )
    if not config.auto_create_character:
        return None
    # Character titles are unique per owner. Reuse a same-name card before
    # create so a script-studio batch (or a second job with the same
    # `subject_name_hint`) does not 422 / drop the output.
    existing = characters_service.find_owned_character_by_name(
        ctx.session, user_id=ctx.job.user_id, name=subject_name
    )
    if existing is not None:
        characters_service.append_reference_asset(
            ctx.session,
            user_id=ctx.job.user_id,
            character_id=existing.id,
            asset_id=asset_id,
            view=view,
            label=label,
        )
        return existing.id
    try:
        character = characters_service.create_character(
            ctx.session,
            user_id=ctx.job.user_id,
            name=subject_name,
            description=None,
            reference_asset_ids=[],
            voice_description=None,
        )
    except ValidationFailed:
        raced = characters_service.find_owned_character_by_name(
            ctx.session, user_id=ctx.job.user_id, name=subject_name
        )
        if raced is None:
            raise
        character = raced
    else:
        ctx.state["created_character_id"] = character.id
    characters_service.append_reference_asset(
        ctx.session,
        user_id=ctx.job.user_id,
        character_id=character.id,
        asset_id=asset_id,
        view=view,
        label=label,
    )
    return character.id


def _link_scene_output(
    ctx: WorkflowContext,
    config: AssetOutputLinkConfig,
    *,
    asset_id: str,
    view: str,
    subject_name: str,
    target_id: str | None,
    label: str | None = None,
) -> str | None:
    """Attaches one output to `target_id`, auto-creating a scene from
    scratch on the first call if there was none — mirrors
    `_link_character_output`'s auto-create branch so a `SCENE` asset-kind
    job without a `target_scene_id` reaches parity with the character path
    instead of leaving the output unattached (the previous, deliberate
    limitation — see `use-generation-submit.ts`'s now-outdated comment).
    Also the fallback when `target_id` no longer resolves, same reason as
    `_link_character_output`'s.

    Returns the id actually used, same threading pattern as
    `_link_character_output`.
    """
    if target_id:
        try:
            scenes_service.append_reference_asset(
                ctx.session,
                user_id=ctx.job.user_id,
                scene_id=str(target_id),
                asset_id=asset_id,
                view=view,
                label=label,
            )
            return target_id
        except NotFound:
            logger.warning(
                "job %s target_scene_id=%s no longer exists; auto-creating a replacement",
                ctx.job.id,
                target_id,
            )
    if not config.auto_create_scene:
        return None
    scene = scenes_service.create_scene(
        ctx.session,
        user_id=ctx.job.user_id,
        name=subject_name,
        description=None,
        reference_asset_ids=[],
    )
    scenes_service.append_reference_asset(
        ctx.session,
        user_id=ctx.job.user_id,
        scene_id=scene.id,
        asset_id=asset_id,
        view=view,
        label=label,
    )
    ctx.state["created_scene_id"] = scene.id
    return scene.id


def _link_character_action_output(
    ctx: WorkflowContext,
    config: AssetOutputLinkConfig,
    *,
    asset_id: str,
    subject_name: str,
    target_id: str | None,
) -> str | None:
    """Attaches one `character_action` video output to `target_id`'s
    `action_clips` list, auto-creating a character from scratch on the first
    call if there was none — mirrors `_link_character_output`'s shape, but
    deliberately calls `characters_service.append_action_clip` (writing
    `params_json["character"]["action_clips"]`), never
    `append_reference_asset` (`reference_assets`): the latter feeds
    `characters_service.apply_character_refs`, which folds every entry
    unfiltered into a *future* job's `reference_asset_ids` — mixing a video
    clip in there would hand it to the next image generation as if it were
    a still reference. Also the fallback when `target_id` no longer
    resolves, same reason as `_link_character_output`'s.

    Same-name reuse mirrors `_link_character_output`'s auto-create branch:
    character titles are unique per owner, so a second `character_action`
    job that lands on the same `subject_name` (explicit hint, or the shared
    "新角色" default) must reuse the owner's existing card instead of racing
    `create_character` into a `ValidationFailed` that used to silently drop
    the clip — this is exactly what happened in production before this fix:
    the output stayed a plain generated asset and `linked_character_id` was
    never set, with no user-visible error.
    """
    if target_id:
        try:
            characters_service.append_action_clip(
                ctx.session,
                user_id=ctx.job.user_id,
                character_id=str(target_id),
                asset_id=asset_id,
            )
            return target_id
        except NotFound:
            logger.warning(
                "job %s target_character_id=%s no longer exists; auto-creating a replacement",
                ctx.job.id,
                target_id,
            )
    if not config.auto_create_character:
        return None
    # Character titles are unique per owner. Reuse a same-name card before
    # create so a second `character_action` job with the same
    # `subject_name_hint` (or the same default) does not 422 / drop the clip.
    existing = characters_service.find_owned_character_by_name(
        ctx.session, user_id=ctx.job.user_id, name=subject_name
    )
    if existing is not None:
        characters_service.append_action_clip(
            ctx.session,
            user_id=ctx.job.user_id,
            character_id=existing.id,
            asset_id=asset_id,
        )
        return existing.id
    try:
        character = characters_service.create_character(
            ctx.session,
            user_id=ctx.job.user_id,
            name=subject_name,
            description=None,
            reference_asset_ids=[],
            voice_description=None,
        )
    except ValidationFailed:
        raced = characters_service.find_owned_character_by_name(
            ctx.session, user_id=ctx.job.user_id, name=subject_name
        )
        if raced is None:
            raise
        character = raced
    else:
        ctx.state["created_character_id"] = character.id
    characters_service.append_action_clip(
        ctx.session,
        user_id=ctx.job.user_id,
        character_id=character.id,
        asset_id=asset_id,
    )
    return character.id


def execute_custom_agent_step(ctx: WorkflowContext, config: CustomAgentStepConfig) -> NodeResult:
    """Runs an operator-created judgment role and parks its output.

    The single port is the point: a role that shipped without a code review
    may inform a later node, but it may not decide the job's fate on its
    own. Nothing here settles credits or transitions state.
    """
    _emit(ctx, JobEventType.PROGRESS, JobStatus.RUNNING, "正在进行智能体判断", 30)
    with _live_thinking(ctx):
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
            # 0, not 1: planning/`copy_generate` can suspend before
            # `route_score` has ever run. Defaulting to 1 here made the
            # resumed walk increment to 2, so the first real
            # `ProviderAttempt` was recorded as attempt 2 (live:
            # `job_01m1608wr7hm49wzdggkynz6ay`).
            "route_attempts": ctx.state.get("route_attempts", 0),
            "attempt_seq": ctx.state.get("attempt_seq", 0),
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
    with _live_thinking(ctx):
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

    with _live_thinking(ctx):
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
        publish=False,
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
    # `route_attempts` is this *pass's* budget (reset per character view by
    # `execute_asset_planning`); `attempt_seq` numbers every attempt across
    # the whole job, so `attempt_number` — which names the output object key
    # `generated/{job_id}/output_{n}.png` — never repeats between views.
    attempts = ctx.state.get("route_attempts", 0) + 1
    ctx.state["route_attempts"] = attempts
    if attempts > config.max_attempts:
        return NodeResult(
            port="retries_exhausted", summary=f"已用尽 {config.max_attempts} 次选路预算"
        )
    attempt_seq = int(ctx.state.get("attempt_seq", 0)) + 1
    ctx.state["attempt_seq"] = attempt_seq
    ctx.state["attempt_number"] = attempt_seq

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
    # `forced_model` (`GenerationParams.forced_model`) opts this job out of
    # `intent_router.select_provider()` entirely — see `router.route()`'s own
    # doc comment. It rides along in `ctx.params` unchanged whether this node
    # was reached by walking the graph from its entry node or jumped to
    # directly by a fast retry (`app.domain.jobs.fast_retry`), so no extra
    # wiring is needed for that path to honor it too.
    forced_model = ctx.params.get("forced_model")
    with _live_thinking(ctx):
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
            forced_model=forced_model if isinstance(forced_model, str) else None,
        )
    ctx.job.routing_trace_json = decision.trace()
    ctx.session.flush()

    if decision.selected is None or decision.capability is None:
        ctx.state["failure_code"] = "PROVIDER_TEMPORARY_FAILURE"
        if decision.reason == "forced_model_unavailable":
            ctx.state["failure_message"] = (
                f"所选模型「{forced_model}」当前不可用，请更换模型或稍后重试。"
            )
        else:
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
        **_resolution_adapt_fields(capability, ctx.params),
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
            "attempt_seq": ctx.state.get("attempt_seq", ctx.state.get("attempt_number", 1)),
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
    """The prompt actually sent: the planner's suggestions folded in (see
    `_planned_prompt`), then any reference-role directive — e.g. telling the
    model a 白膜 motion-guide clip is staging to follow, not footage to copy
    (`app.domain.media.reference_roles`)."""
    prompt, negative_prompt = _planned_prompt(ctx)
    return reference_roles.apply_reference_roles(
        prompt, negative_prompt, ctx.params.get("video_options")
    )


def _planned_prompt(ctx: WorkflowContext) -> tuple[str, str | None]:
    """Folds the planning node's suggestions into what actually gets sent.

    Reads the `PLAN_STATE_KEY` convention key regardless of what
    `PlanningConfig.output_key` a graph configured for the `planning` node —
    a custom graph that renamed it loses this wiring gracefully (no
    enhancement, no error). `prompt_enhancements` and `negative_prompt_
    suggestions` never overwrite the author's own text, only extend it.

    Skipped entirely once `_asset_axis(ctx)` is set (character/scene/cover
    image job, or any video-asset-kind job): `execute_asset_planning` already
    folded its own `asset_kind`/`character_view`-scoped guidance straight
    into `ctx.prompt` earlier in this exact pass. The generic `planning`
    node's plan is blind to that context — same reason its `clarify` sub-step
    is disabled for these kinds (see the `zaolang-generation-jobs` skill's
    asset-pipeline reference on the planning node's clarify slot)
    — and, for a multi-view `CHARACTER` job, it runs exactly once *before*
    the per-view loop even starts, already describing every remaining view
    at once. Folding it in here on every loop pass would leak the other
    view's description into this pass's prompt (a "side" pass's request
    ending up mentioning "back" too) and can also override the real
    reference photo with a physical description the planner invented from
    text alone, since it never sees the attached image's pixels.
    """
    if _asset_axis(ctx) is not None:
        return ctx.prompt, ctx.params.get("negative_prompt")
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


def _stub_video_analysis_result() -> GenerationResult:
    """A settled fake breakdown for a dry run — no `object_key`, matching
    `VideoAnalysisResult`'s shape (`app.api.schemas.jobs`) instead of a
    media artifact's."""
    return GenerationResult(
        succeeded=True,
        output_json={
            "summary": "沙盒预览：整体为一段快节奏城市夜景运镜。",
            "composed_prompt": "霓虹夜色下的城市航拍，缓慢推进，赛博朋克风格",
            "style_tags": ["cyberpunk", "夜景"],
            "pacing": "快节奏剪辑",
            "shots": [
                {
                    "time_range": "00:00-00:03",
                    "camera_movement": "推镜",
                    "scene": "城市天际线",
                    "subject_action": "无人机缓慢前进",
                    "lighting_mood": "霓虹冷色调",
                    "transition_in": "淡入",
                }
            ],
        },
        metadata={"dry_run": True},
    )


def _stub_generation_result(operation: str) -> GenerationResult:
    """A settled fake artifact whose mime matches the operation.

    Quality and the sandbox dialog both inspect mime type; a video dry-run
    that claims to have produced `image/png` looks like a broken provider.
    """
    if operation in (Operation.AUDIO_GENERATION.value, Operation.MUSIC_GENERATION.value):
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


def _requested_group_outputs(ctx: WorkflowContext) -> int:
    """Images one provider call should return: the variant count of a scene
    variant group, else 1."""
    if ctx.params.get("asset_kind") != ImageAssetKind.SCENE.value:
        return 1
    variants = ctx.params.get("scene_variants")
    return len(variants) if isinstance(variants, list) and len(variants) > 1 else 1


def _with_reference_legend(
    prompt: str, references: list[Any], capability: Any, ctx: WorkflowContext
) -> str:
    """Prefixes the "参考图说明" legend naming each labelled reference image
    the provider will receive (`prompt_builder.reference_legend`)."""
    raw_labels = ctx.params.get("reference_labels")
    labels = {
        str(item.get("asset_id")): str(item.get("label"))
        for item in raw_labels or []
        if isinstance(item, dict) and item.get("asset_id") and item.get("label")
    }
    if not labels:
        return prompt
    legend = prompt_builder.reference_legend(
        references, labels, cap=getattr(capability, "max_image_references", None)
    )
    return f"{legend}{prompt}" if legend else prompt


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
        source_work_version_id=ctx.job.source_work_version_id,
    )
    if operation in _REFERENCE_REQUIRED and not references:
        return GenerationResult(
            succeeded=False,
            failure_code="MISSING_REFERENCE",
            metadata={"detail": "reference_asset_ids is required for this operation"},
        )

    effective_prompt, effective_negative_prompt = _plan_enhancements(ctx)
    effective_prompt = _with_reference_legend(
        effective_prompt, references, decision.capability, ctx
    )
    request = GenerationRequest(
        job_id=ctx.job.id,
        operation=operation,
        quality_tier=ctx.job.quality_tier,
        prompt=effective_prompt,
        negative_prompt=effective_negative_prompt,
        seed=ctx.params.get("seed"),
        aspect_ratio=str(ctx.params.get("aspect_ratio") or "16:9"),
        duration_seconds=duration,
        # Client ceiling → this candidate's vendor literal (downgrade, or
        # last-resort lowest). Remix omits the field so the provider default
        # applies — never invent a tier for `wan2.7-videoedit`.
        resolution=_vendor_resolution_for(decision.capability, ctx.params),
        references=references,
        extra=dict(ctx.params.get("extra") or {}),
        output_count=_requested_group_outputs(ctx),
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
        # Resolved before the GENERATING event so the logged prompt is
        # exactly what the provider gets, legend included.
        references = media_service.provider_references_for(
            ctx.session,
            user_id=ctx.job.user_id,
            asset_ids=ctx.params.get("reference_asset_ids") or [],
            video_options=ctx.params.get("video_options"),
            source_work_version_id=ctx.job.source_work_version_id,
        )
        base_prompt = effective_prompt
        effective_prompt = _with_reference_legend(effective_prompt, references, capability, ctx)
        _emit(
            ctx,
            JobEventType.GENERATING,
            JobStatus.SUBMITTED,
            "正在生成",
            40,
            payload={
                "prompt": effective_prompt,
                "base_prompt": base_prompt,
                "negative_prompt": effective_negative_prompt,
                **_resolution_adapt_fields(capability, ctx.params),
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
            # Client ceiling → this candidate's vendor literal. The adapter
            # still receives exactly the spelling its profile table declares
            # (`768P`, `1080p`, …), never the leftover studio token.
            resolution=_vendor_resolution_for(capability, ctx.params),
            references=references,
            extra=dict(ctx.params.get("extra") or {}),
            attempt_number=attempt_number,
            output_count=_requested_group_outputs(ctx),
        )
        ctx.state["requested_outputs"] = request.output_count
        result = decision.provider.submit(request)
        if request.output_count > 1 and result.pending:
            # Group calls are synchronous by contract: a parked async task
            # has no way to carry N outputs through `poll()`.
            result = GenerationResult(
                succeeded=False,
                failure_code="PROVIDER_INVALID_RESPONSE",
                latency_ms=result.latency_ms,
                metadata={**result.metadata, "detail": "group_call_returned_pending"},
            )
        # Priced here, against the endpoint's configuration as it stands right
        # now. Deriving it at report time instead would let tomorrow's price
        # change rewrite what today's generation cost.
        attempt_cost_micro_usd = costs_service.generation_attempt_cost_micro_usd(
            capability.pricing,
            capability=ctx.job.operation,
            request=request,
            billing_profile=capability.billing_profile,
            default_resolution=capability.default_resolution,
            generated_images=result.delivered_outputs if result.succeeded else 1,
        )
        attempt = ProviderAttempt(
            job_id=ctx.job.id,
            provider=capability.name,
            provider_kind=capability.kind,
            model_or_workflow_version=capability.model_or_workflow,
            external_task_id=result.external_task_id,
            attempt_number=attempt_number,
            status=_attempt_status(result),
            cost_minor=result.cost_minor,
            cost_micro_usd=attempt_cost_micro_usd,
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
                    logger.exception("provider.cancel failed after submit for job %s", ctx.job.id)
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
            cost_micro_usd=attempt_cost_micro_usd,
            failure_code=None if result.succeeded else result.failure_code,
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


def execute_video_analysis_generate(
    ctx: WorkflowContext, config: VideoAnalysisGenerateConfig
) -> NodeResult:
    """`video_analysis`'s own generate-and-settle node.

    Mirrors `execute_provider_generate`'s routing/billing/cancel/retry
    skeleton, but the success branch never registers an `Asset` — it writes
    the provider's structured breakdown straight into `ctx.state["result_json"]`
    for `execute_settle_success` to persist onto
    `GenerationJob.analysis_result_json`, and settles the full reserved
    credits directly, since this operation has no downstream
    `quality_check` (a text breakdown has no image/video quality to judge)
    and no partial-duration billing applies (`settlement_credits` only
    adjusts `VIDEO_OPERATIONS`, which `video_analysis` is deliberately not a
    member of — see `app.domain.credits.pricing`).

    The provider call is synchronous today (see `AiHubMixMediaProvider
    ._submit_video_analysis`), so unlike `execute_provider_generate` this
    never suspends on a pending external task; if a future protocol needs
    that, a `result.pending` reply just lands in the same failure/retry
    branch below until `route_score`'s `max_attempts` is exhausted — revisit
    this node before shipping an async video-understanding protocol.
    """
    decision = ctx.state.get("decision")
    if decision is None or decision.capability is None:
        ctx.state["failure_code"] = "PROVIDER_TEMPORARY_FAILURE"
        ctx.state["failure_message"] = "没有可用的解析路线，积分已退回。"
        return NodeResult(port="failed")

    capability = decision.capability
    attempt_number = ctx.state.get("attempt_number", 1)

    if ctx.dry_run:
        _emit(ctx, JobEventType.GENERATING, JobStatus.SUBMITTED, "正在解析视频", 40)
        if ctx.live_provider:
            result = _sandbox_live_generate(ctx, decision)
        else:
            result = _stub_video_analysis_result()
    else:
        if ctx.job.status == JobStatus.QUEUED:
            ctx.job = sm.transition(ctx.session, ctx.job.id, JobStatus.SUBMITTED)
        _emit(ctx, JobEventType.GENERATING, JobStatus.SUBMITTED, "正在解析视频", 40)
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
            prompt=ctx.prompt,
            references=media_service.provider_references_for(
                ctx.session,
                user_id=ctx.job.user_id,
                asset_ids=ctx.params.get("reference_asset_ids") or [],
            ),
            extra=dict(ctx.params.get("extra") or {}),
            attempt_number=attempt_number,
        )
        result = decision.provider.submit(request)
        attempt_cost_micro_usd = costs_service.generation_attempt_cost_micro_usd(
            capability.pricing,
            capability=ctx.job.operation,
            request=request,
            billing_profile=capability.billing_profile,
            default_resolution=capability.default_resolution,
        )
        attempt = ProviderAttempt(
            job_id=ctx.job.id,
            provider=capability.name,
            provider_kind=capability.kind,
            model_or_workflow_version=capability.model_or_workflow,
            external_task_id=result.external_task_id,
            attempt_number=attempt_number,
            status=_attempt_status(result),
            cost_minor=result.cost_minor,
            cost_micro_usd=attempt_cost_micro_usd,
            latency_ms=result.latency_ms,
            failure_code=result.failure_code,
            raw_metadata_redacted_json=result.metadata,
            created_at=utcnow(),
        )
        ctx.session.add(attempt)
        ctx.session.flush()

        ctx.session.refresh(ctx.job)
        if ctx.job.cancel_requested_at is not None:
            attempt.status = ProviderAttemptStatus.CANCELLED
            ctx.session.flush()
            ctx.job = honor_user_cancel(ctx.session, ctx.job)
            return NodeResult(
                port="cancelled", terminal=PipelineOutcome(status=JobStatus.CANCELLED)
            )

        router.record_attempt_outcome(
            ctx.session,
            provider=capability.name,
            operation=ctx.job.operation,
            quality_tier=ctx.job.quality_tier,
            succeeded=result.succeeded,
            latency_ms=result.latency_ms,
            cost_minor=result.cost_minor,
            cost_micro_usd=attempt_cost_micro_usd,
            failure_code=None if result.succeeded else result.failure_code,
        )
        ctx.session.flush()

    if not result.succeeded or not result.output_json:
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
        skip_retry = (ctx.dry_run and ctx.live_provider) or not config.retry_on_failure
        if skip_retry:
            ctx.state["failure_message"] = "视频解析失败，积分已退回。"
            return NodeResult(port="failed", summary=failure_summary)
        return NodeResult(port="retry", summary=failure_summary)

    ctx.state["result_json"] = result.output_json
    ctx.state["actual_credits"] = ctx.job.reserved_credits
    if ctx.dry_run and ctx.live_provider:
        ctx.state["_preview_result_json"] = result.output_json
    _emit(ctx, JobEventType.GENERATING, JobStatus.RUNNING, "解析完成，正在结算", 85)
    return NodeResult(port="succeeded", summary=f"{capability.name} 第 {attempt_number} 次尝试成功")


def _maybe_fill_linked_episode_preview(session: Any, draft: Draft) -> None:
    """Best-effort roster thumbnail after a linked video settles.

    ffmpeg / a missing episode must never fail the job — the list page
    can still call `POST .../preview:from-video`.
    """
    episode_id = (draft.params_json or {}).get("link_episode_id")
    if not isinstance(episode_id, str) or not episode_id:
        return
    from app.domain.editor import service as editor_service
    from app.models import DramaEpisode

    episode = session.get(DramaEpisode, episode_id)
    if episode is None:
        return
    try:
        editor_service.maybe_fill_episode_preview(
            session, episode=episode, actor_user_id=draft.user_id
        )
    except Exception:
        logger.exception("episode preview auto-fill failed for %s", episode_id)


def execute_quality_check(ctx: WorkflowContext, config: QualityCheckConfig) -> NodeResult:
    result = ctx.state.get("result")
    capability = ctx.state.get("capability")
    attempt_number = ctx.state.get("attempt_number", 1)

    _emit(ctx, JobEventType.QUALITY_CHECK, JobStatus.RUNNING, "正在校验输出质量", 78)
    with _live_thinking(ctx):
        outcome = quality.evaluate(
            ctx.session,
            prompt=ctx.prompt,
            output_summary={
                "width": result.width if result else None,
                "height": result.height if result else None,
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
            # Never move `applied_job_id` backward in time — a job that was
            # already in flight when a newer job (or an explicit pin via
            # `apply_draft_version`) took over must not clobber it just
            # because it happens to finish later.
            currently_applied = (
                ctx.session.get(GenerationJob, draft.applied_job_id)
                if draft.applied_job_id
                else None
            )
            if currently_applied is None or currently_applied.created_at <= ctx.job.created_at:
                draft.output_asset_id = asset.id
                draft.applied_job_id = ctx.job.id
                ctx.session.flush()
                _maybe_fill_linked_episode_preview(ctx.session, draft)

    ctx.state["asset_id"] = asset.id
    group_outputs = _register_group_outputs(ctx, result, capability, primary_asset_id=asset.id)
    requested_outputs = max(1, int(ctx.state.get("requested_outputs") or 1))
    ctx.state["actual_credits"] = settlement_credits(
        reserved_credits=ctx.job.reserved_credits,
        operation=ctx.job.operation,
        requested_duration_seconds=int(ctx.params.get("duration_seconds") or 0),
        delivered_duration_ms=result.duration_ms,
        requested_outputs=requested_outputs,
        delivered_outputs=len(group_outputs) if requested_outputs > 1 else 1,
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


def _register_group_outputs(
    ctx: WorkflowContext, result: GenerationResult, capability: Any, *, primary_asset_id: str
) -> list[dict[str, str]]:
    """Registers a group call's extra images and records every image of the
    group, labelled in variant order (`GROUP_LABELS_STATE_KEY`), under
    `GROUP_OUTPUTS_STATE_KEY`. Empty for a single-output call."""
    if not result.extra_outputs:
        ctx.state.pop(GROUP_OUTPUTS_STATE_KEY, None)
        return []
    labels: list[str] = list(ctx.state.get(GROUP_LABELS_STATE_KEY) or [])
    asset_ids = [primary_asset_id]
    for extra in result.extra_outputs:
        asset = media_service.register_generated_asset(
            ctx.session,
            owner_user_id=ctx.job.user_id,
            object_key=extra.object_key,
            mime_type=extra.mime_type,
            width=extra.width,
            height=extra.height,
            duration_ms=None,
            generation_job_id=ctx.job.id,
            provenance={
                "provider": capability.name,
                "model_or_workflow": capability.model_or_workflow,
                "operation": ctx.job.operation,
                "quality_tier": ctx.job.quality_tier,
            },
        )
        asset_ids.append(asset.id)
    outputs = [
        {"asset_id": asset_id, "label": labels[index] if index < len(labels) else ""}
        for index, asset_id in enumerate(asset_ids)
    ]
    ctx.state[GROUP_OUTPUTS_STATE_KEY] = outputs
    return outputs


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
    # `asset_outputs` (populated by `execute_asset_output_advance`) is the
    # richer source once an asset-kind job set it — usually one entry, up to
    # `len(character_views)` for a multi-view `CHARACTER` completion job.
    # Every other operation (video, audio, plain `general` image) never
    # reaches that node type, so `ctx.state["asset_id"]` alone is unchanged.
    outputs = ctx.state.get(ASSET_OUTPUTS_STATE_KEY) or ctx.state.get(GROUP_OUTPUTS_STATE_KEY)
    if outputs:
        asset_ids = [str(o["asset_id"]) for o in outputs if o.get("asset_id")]
        asset_id = asset_ids[0] if asset_ids else None
    else:
        asset_id = ctx.state.get("asset_id")
        asset_ids = [str(asset_id)] if asset_id else []
    # `video_analysis`'s own output: `execute_video_analysis_generate` sets
    # this instead of `asset_id`/`asset_outputs` — the two are mutually
    # exclusive because this operation never registers an `Asset`.
    result_json = ctx.state.get("result_json")

    terminal = PipelineOutcome(
        status=JobStatus.SUCCEEDED,
        asset_id=asset_id,
        asset_ids=asset_ids or None,
        result_json=result_json,
    )
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
        output_asset_ids=asset_ids or None,
        analysis_result_json=result_json,
    )
    _emit(
        ctx,
        JobEventType.SUCCEEDED,
        JobStatus.SUCCEEDED,
        "生成完成",
        100,
        payload={"asset_id": asset_id} if asset_id else {"has_analysis": bool(result_json)},
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
