"""The canvas Agent: read the cards around one, plan, generate, land results.

This is the module that turns the canvas from a board into a creation surface.
It sits between two things that already exist and changes neither:

* Upstream, `agents/canvas_planner.py` produces a plan. It is a language model,
  so nothing it emits is trusted — `_sanitise_plan` is where the guardrails in
  that module's docstring are actually enforced.
* Downstream, `jobs_service.submit` runs the generation. The Agent never calls
  a provider itself, which is what keeps credits, routing, moderation and
  skill context identical to a hand-driven studio request.

Two rules shape the flow:

**Plan, price, then confirm.** A run rests at `awaiting_confirm` with a quote
attached, and `confirm_run` is the only thing that moves credits. There is
deliberately no auto-submit: spending someone's balance without a confirming
tap is what generates refund tickets.

**Refuse before charging, never after.** Every check that could reject a task —
a hallucinated reference, a canvas already at its node cap — runs at plan time.
A job that succeeds, captures credits and then has nowhere to put its result is
the worst outcome available here.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator, MutableMapping
from dataclasses import dataclass
from typing import Any
from weakref import WeakKeyDictionary

from sqlalchemy import event, select, update
from sqlalchemy.orm import Session

from app.agents import canvas_planner
from app.db import rows_affected
from app.domain.canvas import graph_service
from app.domain.canvas import service as canvas_service
from app.domain.errors import (
    AssetRightsRequired,
    CreditsExceedBudget,
    InsufficientCredits,
    NotFound,
    SpendLimitExceeded,
    ValidationFailed,
)
from app.domain.jobs import service as jobs_service
from app.domain.jobs import state_machine as sm
from app.models import (
    CanvasAgentRun,
    CanvasAgentTask,
    CanvasEdge,
    CanvasNode,
    CanvasProject,
    GenerationJob,
)
from app.models.base import utcnow
from app.models.enums import (
    CANVAS_AGENT_RUN_TRANSITIONS,
    CanvasAgentRunStatus,
    CanvasAgentTaskStatus,
    CanvasNodeKind,
    JobStatus,
    Operation,
    QualityTier,
)

# --------------------------------------------------------------------------
# Caps
# --------------------------------------------------------------------------

# How far back along the edges the planner is shown. An unbounded walk on a
# 2000-card canvas builds a prompt nobody can afford and no context window
# holds; three hops is enough for "this shot, its reference, and where that
# came from".
MAX_CONTEXT_DEPTH = 3
MAX_CONTEXT_NODES = 12
# Card text is author-written and can be a whole scene. Truncated per card so
# one long note cannot crowd out the other eleven.
MAX_CONTEXT_TEXT = 600
# Every task is real money, so the ceiling is low and the caller may lower it
# further.
MAX_TASKS_PER_RUN = 4

# Where results land relative to the agent card. Laid out at plan time so the
# user sees where output will appear, and so tasks finishing out of order still
# land where they were promised.
DROP_OFFSET_X = 360
DROP_SPACING_Y = 220

_PLANNABLE = frozenset(canvas_planner.PLANNABLE_OPERATIONS)
# The planner may pick a cheaper tier than the user did, never a dearer one.
_TIER_RANK = {QualityTier.PREVIEW: 0, QualityTier.STANDARD: 1, QualityTier.CINEMATIC: 2}
_VIDEO_OPERATIONS = frozenset({Operation.TEXT_TO_VIDEO, Operation.IMAGE_TO_VIDEO})
_NEEDS_REFERENCE = frozenset({Operation.IMAGE_TO_IMAGE, Operation.IMAGE_TO_VIDEO})
DEFAULT_VIDEO_SECONDS = 5

# Rejections `jobs_service.submit` raises *before* it writes anything, so the
# task can be skipped and the batch carried on. Everything else — notably the
# `Conflict` raised after an internal `session.rollback()` — must propagate.
SKIPPABLE = (
    InsufficientCredits,
    SpendLimitExceeded,
    CreditsExceedBudget,
    ValidationFailed,
    AssetRightsRequired,
    NotFound,
)


@dataclass(frozen=True, slots=True)
class PlannedTask:
    operation: str
    quality_tier: str
    params: dict[str, Any]
    drop_x: int
    drop_y: int


# --------------------------------------------------------------------------
# Context
# --------------------------------------------------------------------------


def _card_text(node: CanvasNode) -> str:
    data = node.data_json or {}
    parts = [data.get("label"), data.get("text")]
    joined = " ".join(str(part) for part in parts if isinstance(part, str) and part.strip())
    return joined[:MAX_CONTEXT_TEXT]


def upstream_context(
    session: Session, *, canvas_id: str, node_id: str
) -> tuple[list[str], dict[str, Any]]:
    """The selected card plus what feeds it, breadth-first and bounded.

    Breadth-first rather than depth-first so the caps spend the budget on the
    cards *nearest* the one the user selected — those are the ones they meant.
    The walk reads `ix_canvas_edges_canvas_id_target_node_id`, which is the
    concrete reason edges are rows rather than entries in a JSON blob.
    """
    root = session.get(CanvasNode, node_id)
    if root is None or root.canvas_id != canvas_id:
        raise NotFound("画布节点不存在。")

    ordered: list[CanvasNode] = [root]
    seen = {root.id}
    frontier = [root.id]

    for _ in range(MAX_CONTEXT_DEPTH):
        if not frontier or len(ordered) >= MAX_CONTEXT_NODES:
            break
        sources = list(
            session.scalars(
                select(CanvasEdge.source_node_id).where(
                    CanvasEdge.canvas_id == canvas_id,
                    CanvasEdge.target_node_id.in_(frontier),
                )
            )
        )
        pending = [source for source in dict.fromkeys(sources) if source not in seen]
        if not pending:
            break
        rows = list(
            session.scalars(
                select(CanvasNode).where(
                    CanvasNode.canvas_id == canvas_id, CanvasNode.id.in_(pending)
                )
            )
        )
        # Stable order regardless of how the database returned them, so a
        # replayed run sees the same context.
        rows.sort(key=lambda item: (item.seq, item.id))
        next_frontier: list[str] = []
        for row in rows:
            if len(ordered) >= MAX_CONTEXT_NODES:
                break
            ordered.append(row)
            seen.add(row.id)
            next_frontier.append(row.id)
        frontier = next_frontier

    digest = {
        "selected_node_id": root.id,
        "nodes": [
            {
                "id": node.id,
                "kind": node.node_kind,
                "role": "selected" if node.id == root.id else "upstream",
                "text": _card_text(node),
                # Named `asset_id` rather than nested under `binding` so the
                # planner has one obvious place to read a reference from.
                **({"asset_id": node.binding_asset_id} if node.binding_asset_id else {}),
            }
            for node in ordered
        ],
    }
    return [node.id for node in ordered], digest


def _available_asset_ids(digest: dict[str, Any]) -> set[str]:
    return {
        node["asset_id"]
        for node in digest.get("nodes") or []
        if isinstance(node, dict) and isinstance(node.get("asset_id"), str)
    }


# --------------------------------------------------------------------------
# Plan sanitising
# --------------------------------------------------------------------------


def _clean_text(value: Any, *, limit: int) -> str:
    return str(value).strip()[:limit] if isinstance(value, str) else ""


def _as_tier(value: str) -> QualityTier | None:
    """A tier the planner named, or None if it named nothing recognisable."""
    try:
        return QualityTier(value)
    except ValueError:
        return None


def _sanitise_plan(
    raw: dict[str, Any],
    *,
    digest: dict[str, Any],
    tier_ceiling: str,
    max_tasks: int,
    origin: tuple[int, int],
) -> list[PlannedTask]:
    """Turn model output into tasks that are safe to price and submit.

    Everything here is a rejection the *user* would otherwise pay for, so each
    check drops the offending task rather than repairing it into something they
    did not ask for.
    """
    tasks_raw = raw.get("tasks")
    if not isinstance(tasks_raw, list):
        return []

    available = _available_asset_ids(digest)
    ceiling_rank = _TIER_RANK.get(QualityTier(tier_ceiling), 1)
    planned: list[PlannedTask] = []

    for entry in tasks_raw:
        if len(planned) >= max_tasks:
            break
        if not isinstance(entry, dict):
            continue

        operation = _clean_text(entry.get("operation"), limit=32)
        if operation not in _PLANNABLE:
            continue
        prompt = _clean_text(entry.get("prompt"), limit=4096)
        if not prompt:
            continue

        # A hallucinated asset id would otherwise surface from deep inside
        # `submit` as a generic reference failure. Dropping unknown ids here
        # keeps the error legible and the request honest.
        references = [
            ref
            for ref in (entry.get("reference_asset_ids") or [])
            if isinstance(ref, str) and ref in available
        ][:9]

        op = Operation(operation)
        if op in _NEEDS_REFERENCE and not references:
            # The planner asked to edit an image it cannot name. Rewriting it
            # to a text-to-image would silently produce something else.
            continue

        params: dict[str, Any] = {"prompt": prompt}
        negative = _clean_text(entry.get("negative_prompt"), limit=1024)
        if negative:
            params["negative_prompt"] = negative
        aspect = _clean_text(entry.get("aspect_ratio"), limit=16)
        if aspect:
            params["aspect_ratio"] = aspect
        if references:
            params["reference_asset_ids"] = references
        if op in _VIDEO_OPERATIONS:
            raw_seconds = entry.get("duration_seconds")
            seconds = (
                int(raw_seconds)
                if isinstance(raw_seconds, (int, float)) and not isinstance(raw_seconds, bool)
                else DEFAULT_VIDEO_SECONDS
            )
            params["duration_seconds"] = max(1, min(seconds, 10))

        # Never above the ceiling, and `forced_model` is not read at all — it
        # is absent from the planner's schema, and honouring it here would
        # reopen the hole that keeps shut.
        tier = tier_ceiling
        candidate = _as_tier(_clean_text(entry.get("quality_tier"), limit=24))
        if candidate is not None and _TIER_RANK[candidate] < ceiling_rank:
            tier = candidate.value

        index = len(planned)
        planned.append(
            PlannedTask(
                operation=op.value,
                quality_tier=tier,
                params=params,
                drop_x=origin[0] + DROP_OFFSET_X,
                drop_y=origin[1] + index * DROP_SPACING_Y,
            )
        )

    return planned


# --------------------------------------------------------------------------
# Running
# --------------------------------------------------------------------------


def prepare_plan(
    session: Session,
    *,
    user_id: str,
    canvas_id: str,
    agent_node_id: str,
    goal: str,
    quality_tier: str,
    max_tasks: int,
) -> tuple[CanvasProject, CanvasNode, dict[str, Any], list[str], Iterator[Any], Any]:
    """Validate, build context, and open the planning stream.

    Returns everything the route needs to persist the run once the stream has
    drained. Nothing is written here: a plan that never completes should leave
    no row behind.
    """
    clean_goal = (goal or "").strip()
    if not clean_goal:
        raise ValidationFailed("请描述你想让助手做什么。")
    if len(clean_goal) > 2000:
        raise ValidationFailed("目标描述过长。")
    if max_tasks < 1 or max_tasks > MAX_TASKS_PER_RUN:
        raise ValidationFailed(f"一次最多规划 {MAX_TASKS_PER_RUN} 个任务。")

    project = canvas_service.get_project(session, user_id=user_id, canvas_id=canvas_id)
    node = session.get(CanvasNode, agent_node_id)
    if node is None or node.canvas_id != project.id:
        raise NotFound("画布节点不存在。")

    # Checked before a single credit moves. A run whose results could not fit
    # would otherwise be discovered only after the jobs had been paid for.
    room = graph_service.MAX_NODES - graph_service.node_count(session, project.id)
    if room < max_tasks:
        raise ValidationFailed("画布节点已接近上限，请先清理后再让助手生成。")

    node_ids, digest = upstream_context(session, canvas_id=project.id, node_id=node.id)
    chunks, finalize = canvas_planner.stream_plan_canvas(
        session,
        user_id=user_id,
        goal=clean_goal,
        context=digest,
        max_tasks=max_tasks,
        quality_tier=quality_tier,
    )
    return project, node, digest, node_ids, chunks, finalize


def persist_run(
    session: Session,
    *,
    user_id: str,
    canvas_id: str,
    agent_node_id: str,
    goal: str,
    quality_tier: str,
    max_tasks: int,
    digest: dict[str, Any],
    context_node_ids: list[str],
    origin: tuple[int, int],
    outcome: Any,
) -> CanvasAgentRun:
    """Write the run and its tasks, priced and awaiting confirmation."""
    raw = getattr(outcome, "data", None)
    if not isinstance(raw, dict):
        raw = {}
    planned = _sanitise_plan(
        raw,
        digest=digest,
        tier_ceiling=quality_tier,
        max_tasks=max_tasks,
        origin=origin,
    )

    run = CanvasAgentRun(
        canvas_id=canvas_id,
        user_id=user_id,
        goal=goal.strip(),
        agent_node_id=agent_node_id,
        context_node_ids_json=context_node_ids,
        context_digest_json=digest,
        plan_json={
            "summary": _clean_text(raw.get("summary"), limit=1000),
            "raw_tasks": raw.get("tasks") or [],
        },
        planner_agent_run_id=getattr(outcome, "agent_run_id", None),
        model=getattr(outcome, "model", None) or None,
        started_at=utcnow(),
    )

    if not planned:
        # An empty plan is a failed run, not one awaiting a confirmation the
        # user cannot give. Nothing was charged.
        run.status = CanvasAgentRunStatus.FAILED.value
        run.failure_code = "NO_TASKS"
        run.failure_message = "助手没有给出可执行的生成任务，请把目标写得更具体一些。"
        run.finished_at = utcnow()
        session.add(run)
        session.flush()
        return run

    total = 0
    session.add(run)
    session.flush()
    for index, task in enumerate(planned):
        quote = jobs_service.quote_for(
            session,
            operation=task.operation,
            quality_tier=task.quality_tier,
            duration_seconds=int(task.params.get("duration_seconds") or 0),
        )
        total += quote.credits
        session.add(
            CanvasAgentTask(
                run_id=run.id,
                ordinal=index,
                operation=task.operation,
                quality_tier=task.quality_tier,
                request_json=task.params,
                drop_x=task.drop_x,
                drop_y=task.drop_y,
            )
        )

    run.quoted_credits = total
    run.status = CanvasAgentRunStatus.AWAITING_CONFIRM.value
    session.flush()
    return run


def get_run(session: Session, *, user_id: str, run_id: str) -> CanvasAgentRun:
    run = session.get(CanvasAgentRun, run_id)
    if run is None:
        raise NotFound("助手运行记录不存在。")
    # Access follows the canvas, not the run's own author: a co-creator who can
    # arrange the canvas can also see what the Agent did on it.
    canvas_service.get_project(session, user_id=user_id, canvas_id=run.canvas_id)
    return run


def list_runs(session: Session, *, user_id: str, canvas_id: str) -> list[CanvasAgentRun]:
    project = canvas_service.get_project(session, user_id=user_id, canvas_id=canvas_id)
    return list(
        session.scalars(
            select(CanvasAgentRun)
            .where(CanvasAgentRun.canvas_id == project.id)
            .order_by(CanvasAgentRun.created_at.desc())
            .limit(50)
        )
    )


def tasks_for(session: Session, run_id: str) -> list[CanvasAgentTask]:
    return list(
        session.scalars(
            select(CanvasAgentTask)
            .where(CanvasAgentTask.run_id == run_id)
            .order_by(CanvasAgentTask.ordinal)
        )
    )


def _set_run_status(session: Session, run: CanvasAgentRun, target: CanvasAgentRunStatus) -> bool:
    """Conditional transition, so two confirms cannot both submit.

    Same shape as the job state machine: legal source states go in the WHERE
    clause, and the row count is the answer to "was this move allowed".
    """
    sources = [
        source.value
        for source, allowed in CANVAS_AGENT_RUN_TRANSITIONS.items()
        if target in allowed
    ]
    if not sources:
        return False

    values: dict[str, Any] = {"status": target.value}
    if target.is_terminal:
        values["finished_at"] = utcnow()
    matched = rows_affected(
        session,
        update(CanvasAgentRun)
        .where(CanvasAgentRun.id == run.id, CanvasAgentRun.status.in_(sources))
        .values(**values),
    )
    if matched == 1:
        session.expire(run)
        return True
    return False


def confirm_run(
    session: Session, *, user_id: str, run_id: str
) -> tuple[CanvasAgentRun, list[GenerationJob]]:
    """Submit every planned task as a real generation job.

    The conditional transition to `submitting` is what makes a double-tapped
    confirm produce one set of jobs rather than two sets of reservations.

    Returns the run and the jobs the caller must enqueue after committing.
    Handing them back rather than dispatching here is not a preference: a
    broker that picks a job up before its row is visible finds nothing.
    """
    run = get_run(session, user_id=user_id, run_id=run_id)
    if run.user_id != user_id:
        # Planning spends the run author's context and confirming spends their
        # credits, so only they may confirm — a co-creator can watch it, and
        # start their own.
        raise NotFound("助手运行记录不存在。")
    if not _set_run_status(session, run, CanvasAgentRunStatus.SUBMITTING):
        raise ValidationFailed("该助手任务已经提交过或已结束。")

    submitted = 0
    # Jobs to hand to the broker, collected here and dispatched by the caller
    # *after* it commits — a worker that picked one up before its row was
    # visible would find nothing.
    dispatched: list[GenerationJob] = []
    for task in tasks_for(session, run.id):
        if task.status != CanvasAgentTaskStatus.PLANNED:
            continue
        try:
            result = jobs_service.submit(
                session,
                user_id=user_id,
                operation=task.operation,
                quality_tier=task.quality_tier,
                params=dict(task.request_json or {}),
                # Deterministic per task, so a retried confirm replays the same
                # job instead of reserving a second lot of credits.
                idempotency_key=f"canvas-agent:{task.id}",
                max_credits=run.max_credits,
            )
        except SKIPPABLE as exc:
            # Only rejections raised *before* `submit` writes anything are
            # skippable. A broad `except Exception` here would also swallow the
            # `Conflict` that `submit` raises after calling `session.rollback()`
            # — and continuing the loop past that point would silently discard
            # this run's own status change and every task already submitted.
            # Anything else propagates; the run stays at `submitting` and the
            # user can cancel it.
            task.status = CanvasAgentTaskStatus.SKIPPED.value
            task.failure_code = type(exc).__name__
            task.failure_message = str(getattr(exc, "message", exc))[:500]
            continue
        task.generation_job_id = result.job.id
        task.status = CanvasAgentTaskStatus.SUBMITTED.value
        submitted += 1
        if not result.replayed:
            dispatched.append(result.job)

    session.flush()
    if submitted == 0:
        _set_run_status(session, run, CanvasAgentRunStatus.FAILED)
        run.failure_code = "NO_TASKS_SUBMITTED"
        run.failure_message = "所有任务都未能提交，积分未被扣除。"
    else:
        _set_run_status(session, run, CanvasAgentRunStatus.RUNNING)
    session.flush()
    return run, dispatched


def cancel_run(session: Session, *, user_id: str, run_id: str) -> CanvasAgentRun:
    """Cancel a run and ask its non-terminal jobs to stop.

    Jobs already in flight are *requested* to cancel rather than killed: the
    pipeline owns whether a provider call can still be abandoned, and the
    credit settlement that goes with it.
    """
    run = get_run(session, user_id=user_id, run_id=run_id)
    if run.user_id != user_id:
        raise NotFound("助手运行记录不存在。")
    if CanvasAgentRunStatus(run.status).is_terminal:
        return run

    for task in tasks_for(session, run.id):
        if CanvasAgentTaskStatus(task.status).is_terminal:
            continue
        if task.generation_job_id:
            # A job already past the point of cancelling is a normal outcome,
            # not a failure of this request.
            with contextlib.suppress(Exception):
                sm.request_cancel(session, task.generation_job_id)
        task.status = CanvasAgentTaskStatus.CANCELLED.value

    _set_run_status(session, run, CanvasAgentRunStatus.CANCELLED)
    session.flush()
    return run


# --------------------------------------------------------------------------
# Landing results
# --------------------------------------------------------------------------


def _run_outcome(tasks: list[CanvasAgentTask]) -> CanvasAgentRunStatus | None:
    """The run's verdict once every task has settled, or None while any is live."""
    if any(not CanvasAgentTaskStatus(task.status).is_terminal for task in tasks):
        return None
    landed = sum(1 for task in tasks if task.status == CanvasAgentTaskStatus.LANDED)
    if landed == len(tasks):
        return CanvasAgentRunStatus.SUCCEEDED
    if landed == 0:
        return CanvasAgentRunStatus.FAILED
    # Some results are on the canvas. Calling that a failure would tell the
    # user their work is gone when it is sitting right in front of them.
    return CanvasAgentRunStatus.PARTIAL


def land_job_result(session: Session, *, job: GenerationJob) -> None:
    """Turn a finished generation into a card on the canvas that asked for it.

    Called from `jobs.completion.on_job_terminal`, which every terminal write
    funnels through — so this runs for failures and cancellations too, and a
    task that will never produce a card flips to an error state instead of
    spinning forever.

    Landing is guarded by a conditional UPDATE on `result_node_id IS NULL`,
    the same `rows_affected` trick the job state machine uses on itself. A
    redelivered terminal transition therefore cannot insert the card twice.
    """
    task = session.scalar(
        select(CanvasAgentTask).where(CanvasAgentTask.generation_job_id == job.id)
    )
    if task is None or CanvasAgentTaskStatus(task.status).is_terminal:
        return

    run = session.get(CanvasAgentRun, task.run_id)
    if run is None:  # pragma: no cover - cascade would have taken the task too
        return

    status = JobStatus(job.status)
    is_video = task.operation in (
        Operation.TEXT_TO_VIDEO.value,
        Operation.IMAGE_TO_VIDEO.value,
    )
    if status is JobStatus.SUCCEEDED and job.output_asset_id:
        # Claim the task first. Losing this race means another worker already
        # landed the card, and inserting a second one is exactly what the guard
        # exists to prevent.
        claimed = rows_affected(
            session,
            update(CanvasAgentTask)
            .where(
                CanvasAgentTask.id == task.id,
                CanvasAgentTask.result_node_id.is_(None),
                CanvasAgentTask.status != CanvasAgentTaskStatus.LANDED.value,
            )
            .values(status=CanvasAgentTaskStatus.LANDED.value),
        )
        if claimed != 1:
            return
        node, changes = graph_service.insert_agent_node(
            session,
            canvas_id=run.canvas_id,
            node_kind=CanvasNodeKind.VIDEO if is_video else CanvasNodeKind.IMAGE,
            position=(task.drop_x, task.drop_y),
            # The binding kind has to match the card kind. They are read
            # independently — `graph-convert.ts` resolves the thumbnail off the
            # binding and the badge off the node kind — so a video card
            # carrying an image binding is data that contradicts itself.
            binding={
                "kind": "video" if is_video else "image",
                "asset_id": job.output_asset_id,
            },
            data={"label": (task.request_json or {}).get("prompt", "")[:120]},
            source_node_id=run.agent_node_id,
            actor_user_id=run.user_id,
        )
        session.flush()
        task.result_node_id = node.id
        # Published on this session's own commit — see `_queue_frames`.
        _queue_frames(session, run.canvas_id, changes)
    elif status is JobStatus.CANCELLED:
        task.status = CanvasAgentTaskStatus.CANCELLED.value
    elif status.is_terminal:
        task.status = CanvasAgentTaskStatus.FAILED.value
        task.failure_code = job.failure_code
        task.failure_message = job.failure_message
    else:
        return

    session.flush()
    outcome = _run_outcome(tasks_for(session, run.id))
    if outcome is not None:
        _set_run_status(session, run, outcome)
    session.flush()


def restore_task_card(session: Session, *, user_id: str, task_id: str) -> CanvasNode:
    """Put a landed result back on the canvas after its card was deleted.

    Results land by themselves (`land_job_result`); this exists only for the
    case where the user then removed the card and wants it back. It is the one
    place a *user action* re-runs the landing insert, so it re-checks that the
    card is genuinely gone rather than trusting the client: `result_node_id`
    survives the delete (the FK is `SET NULL`… but only for the row it points
    at, so a stale non-null id is exactly what "deleted" looks like here).
    """
    task = session.get(CanvasAgentTask, task_id)
    if task is None:
        raise NotFound("助手任务不存在。")
    run = session.get(CanvasAgentRun, task.run_id)
    if run is None:  # pragma: no cover - cascade would have taken the task
        raise NotFound("助手任务不存在。")
    # Access follows the canvas, as everywhere else in this module.
    canvas_service.get_project(session, user_id=user_id, canvas_id=run.canvas_id)

    if task.status != CanvasAgentTaskStatus.LANDED:
        raise ValidationFailed("这条任务还没有产出可以放回画布的结果。")
    if task.result_node_id and session.get(CanvasNode, task.result_node_id) is not None:
        raise ValidationFailed("这张卡片还在画布上。")

    job = session.get(GenerationJob, task.generation_job_id) if task.generation_job_id else None
    if job is None or not job.output_asset_id:
        raise ValidationFailed("找不到这条任务的产出。")

    is_video = task.operation in (
        Operation.TEXT_TO_VIDEO.value,
        Operation.IMAGE_TO_VIDEO.value,
    )
    node, changes = graph_service.insert_agent_node(
        session,
        canvas_id=run.canvas_id,
        node_kind=CanvasNodeKind.VIDEO if is_video else CanvasNodeKind.IMAGE,
        position=(task.drop_x, task.drop_y),
        binding={
            "kind": "video" if is_video else "image",
            "asset_id": job.output_asset_id,
        },
        data={"label": (task.request_json or {}).get("prompt", "")[:120]},
        source_node_id=run.agent_node_id,
        actor_user_id=run.user_id,
    )
    session.flush()
    task.result_node_id = node.id
    _queue_frames(session, run.canvas_id, changes)
    session.flush()
    return node


# Frames produced while a worker's transaction is still open.
#
# They cannot be published from inside it: announcing a write that then rolls
# back would have every open window render a card the database never kept. But
# requiring each caller to remember a `publish_pending()` after its commit is
# the kind of rule that holds until someone adds a fourth call site — so the
# publish is attached to the session's own `after_commit` instead. It fires
# exactly when the transaction lands, never on a rollback, and no caller has to
# know it exists.
#
# Keyed on the session object, in a weak map rather than by `id()`. A session
# that is garbage-collected without ever committing or rolling back would
# otherwise leave its entry behind, and CPython reuses object ids — so a later
# session landing on the same id would publish a different canvas's frames.
_PENDING: MutableMapping[Session, list[tuple[str, dict[str, Any]]]] = WeakKeyDictionary()


def _queue_frames(session: Session, canvas_id: str, changes: list[Any]) -> None:
    pending = _PENDING.get(session)
    first = pending is None
    if pending is None:
        pending = []
        _PENDING[session] = pending
    pending.extend((canvas_id, graph_service.change_payload(change)) for change in changes)
    if not first:
        return

    def _flush(inner: Session) -> None:
        for pending_canvas_id, frame in _PENDING.pop(inner, []):
            graph_service.publish_changes(pending_canvas_id, [frame])

    def _drop(inner: Session) -> None:
        _PENDING.pop(inner, None)

    # Registered once per session, and only for a session that actually has
    # something to say.
    event.listen(session, "after_commit", _flush, once=True)
    event.listen(session, "after_rollback", _drop, once=True)


__all__ = [
    "DROP_OFFSET_X",
    "DROP_SPACING_Y",
    "MAX_CONTEXT_DEPTH",
    "MAX_CONTEXT_NODES",
    "MAX_TASKS_PER_RUN",
    "PlannedTask",
    "cancel_run",
    "confirm_run",
    "get_run",
    "land_job_result",
    "list_runs",
    "persist_run",
    "prepare_plan",
    "restore_task_card",
    "tasks_for",
    "upstream_context",
]
