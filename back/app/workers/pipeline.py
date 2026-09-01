"""The generation pipeline entry point.

Runs as a plain function so it can be executed inline by tests and integration
runs without a broker, while the Celery task in `tasks.py` is a thin wrapper
around it. The actual step-by-step logic now lives in the configurable
`WorkflowRunner` (`app/workflows/runner.py`): this module's job is just to
resolve *which* graph a job runs (its pinned template, the operation's active
template, or the code-level default, in that order) and to keep the one
top-level crash contract Celery depends on — release credits, mark the job
failed, then re-raise. Missing jobs raise ``JobNotFoundError`` (no retry);
transient DB/network faults are retried by the Celery wrapper.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.domain.jobs import fast_retry
from app.domain.jobs import service as jobs_service
from app.domain.jobs import state_machine as sm
from app.domain.system_log import service as system_log
from app.domain.workflow_templates import service as workflow_templates_service
from app.models import GenerationJob, GenerationWorkflowTemplate
from app.models.enums import JobStatus, Operation, SystemLogLevel, SystemLogSource
from app.observability.context import set_job_id
from app.workflows.configs import RouteScoreConfig
from app.workflows.defaults import default_graph, video_analysis_graph
from app.workflows.graph import WorkflowGraph
from app.workflows.runner import WorkflowRunner
from app.workflows.types import PipelineOutcome, WorkflowContext

__all__ = [
    "MAX_PROVIDER_ATTEMPTS",
    "JobNotFoundError",
    "PipelineOutcome",
    "resolve_graph",
    "resume_after_input",
    "run_generation_pipeline",
]

logger = logging.getLogger(__name__)

# The default template's `route_score` node budget — kept as a module-level
# constant only because it is a convenient single fact for tests and ops
# docs to reference; the actual budget any given job runs with is whatever
# its `route_score` node's `max_attempts` config says.
MAX_PROVIDER_ATTEMPTS: int = RouteScoreConfig.model_fields["max_attempts"].default


class JobNotFoundError(LookupError):
    """Celery message references a ``generation_jobs`` row that no longer exists.

    Distinct from other ``LookupError`` subclasses (e.g. unknown tools) so the
    worker can drop orphan broker messages without retrying them.
    """


def run_generation_pipeline(session: Session, job_id: str) -> PipelineOutcome:
    job = session.get(GenerationJob, job_id)
    if job is None:
        raise JobNotFoundError(f"job {job_id} not found")
    set_job_id(job.id)

    if JobStatus(job.status).is_terminal:
        logger.info("job %s already terminal (%s)", job.id, job.status)
        return PipelineOutcome(status=JobStatus(job.status))

    try:
        graph = resolve_graph(session, job)
        params = dict(job.request_json)
        ctx = WorkflowContext(
            session=session, job=job, prompt=str(params.get("prompt", "")), params=params
        )
        start_node_id = _apply_fast_retry_seed(session, ctx, graph)
        return WorkflowRunner(graph).run(ctx, start_node_id=start_node_id)
    except Exception as exc:
        logger.exception("pipeline crashed for job %s", job.id)
        # The only durable record of what actually crashed: `JobEvent`
        # deliberately gets a scrubbed `public_message` (see `_fail`) so it
        # never leaks internals to the C-end caller, and this is not a retry
        # Celery will re-raise into (this is the top-level catch-all, not
        # `tasks.py`'s per-attempt boundary), so `logger.exception` alone
        # would leave an operator with nothing to look up after the fact.
        system_log.emit(
            source=SystemLogSource.PIPELINE,
            event="pipeline_crashed",
            message=str(exc),
            dedup_key=f"job:{job.id}",
            level=SystemLogLevel.ERROR,
            job_id=job.id,
            details={"exception_type": type(exc).__name__},
        )
        _fail(session, job, code="INTERNAL_ERROR", message="生成过程出现异常，积分已退回。")
        raise exc from None


def _apply_fast_retry_seed(
    session: Session, ctx: WorkflowContext, graph: WorkflowGraph
) -> str | None:
    """Seeds `ctx` and returns the `route_score` node id when this run
    qualifies for a fast retry (`app.domain.jobs.fast_retry`), else `None`.

    Never raises and never blocks the normal path: a graph that doesn't have
    exactly one `route_score` node (a custom template with a different shape)
    just falls back to walking from the entry node like any other job.
    """
    if ctx.dry_run:
        return None
    seed = fast_retry.build_seed(session, ctx.job)
    if seed is None:
        return None
    route_score_ids = [node.id for node in graph.nodes if node.type == "route_score"]
    if len(route_score_ids) != 1:
        return None

    ctx.prompt = seed.prompt
    if seed.negative_prompt is not None:
        ctx.params["negative_prompt"] = seed.negative_prompt
    ctx.state["tried_providers"] = set(seed.tried_providers)
    system_log.emit(
        source=SystemLogSource.PIPELINE,
        event="fast_retry_used",
        message=f"job={ctx.job.id} skips pre-checks, excludes {sorted(seed.tried_providers)}",
        dedup_key=f"job:{ctx.job.id}:fast_retry",
        level=SystemLogLevel.INFO,
        job_id=ctx.job.id,
        details={"excluded_providers": sorted(seed.tried_providers)},
    )
    return route_score_ids[0]


def resume_after_input(
    job: GenerationJob, ctx: WorkflowContext, *, node_id: str
) -> PipelineOutcome:
    """Continues the graph from the node that parked on `AWAITING_INPUT`.

    Shared by the C-end and admin answer endpoints so a sandbox try-it
    resumes the same way a C-end job does, including `graph_override_json`.
    """
    return WorkflowRunner(resolve_graph(ctx.session, job)).resume(ctx, node_id=node_id, port="ok")


def resolve_graph(session: Session, job: GenerationJob) -> WorkflowGraph:
    """Which graph this job runs, in order of precedence.

    Public because resuming a suspended job (`workers/async_polling.py`) has
    to land in the very same graph the earlier run was walking, which the
    precedence below already guarantees by preferring the pinned template.

    1. A sandbox try-it's unpublished canvas snapshot (`graph_override_json`)
       — never pins or backfills the live template, so a publish mid-run
       cannot change what the try-it walked.
    2. The template already pinned on the job (set at submission, or by a
       previous call to this function for a legacy row) — never changes
       mid-flight even if an admin publishes a new version.
    3. The operation's current active template, backfilled onto the job so a
       retry/resume of the same job keeps using it — covers rows created
       before `workflow_template_id` existed.
    4. The code-level default shape, used only when no template has ever been
       published for this operation (a fresh deploy before `make seed`, or a
       test that builds a job without going through the seed script).
    """
    if job.graph_override_json:
        return WorkflowGraph.from_dict(job.graph_override_json)

    template: GenerationWorkflowTemplate | None = None
    if job.workflow_template_id:
        template = session.get(GenerationWorkflowTemplate, job.workflow_template_id)

    if template is None:
        template = workflow_templates_service.get_active(session, job.operation)
        if template is not None:
            job.workflow_template_id = template.id
            session.flush()

    if template is not None:
        return WorkflowGraph.from_dict(template.graph_json)
    if job.operation == Operation.VIDEO_ANALYSIS.value:
        return WorkflowGraph.from_dict(video_analysis_graph(session))
    return WorkflowGraph.from_dict(default_graph(session))


def _fail(session: Session, job: GenerationJob, *, code: str, message: str) -> None:
    """Terminal failure for a crash the runner never got a chance to handle.

    Safe to call on a job the runner already failed: `settle_release` is a
    no-op on an already-settled reservation and a transition into `FAILED`
    from `FAILED` is simply swallowed below, matching `state_machine`'s
    conditional-update guarantee that only the first terminal write wins.
    """
    jobs_service.settle_release(session, job, reason=code)
    try:
        sm.transition(session, job.id, JobStatus.FAILED, failure_code=code, failure_message=message)
    except Exception:
        logger.exception("could not mark job %s failed", job.id)
