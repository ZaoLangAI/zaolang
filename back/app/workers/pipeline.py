"""The generation pipeline entry point.

Runs as a plain function so it can be executed inline by tests and integration
runs without a broker, while the Celery task in `tasks.py` is a thin wrapper
around it. The actual step-by-step logic now lives in the configurable
`WorkflowRunner` (`app/workflows/runner.py`): this module's job is just to
resolve *which* graph a job runs (its pinned template, the operation's active
template, or the code-level default, in that order) and to keep the one
top-level crash contract Celery depends on — release credits, mark the job
failed, then re-raise so `tasks.run_generation`'s `self.retry` still fires for
a genuine infrastructure fault.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.domain.jobs import service as jobs_service
from app.domain.jobs import state_machine as sm
from app.domain.workflow_templates import service as workflow_templates_service
from app.models import GenerationJob, GenerationWorkflowTemplate
from app.models.enums import JobStatus
from app.observability.context import set_job_id
from app.workflows.configs import RouteScoreConfig
from app.workflows.defaults import default_graph
from app.workflows.graph import WorkflowGraph
from app.workflows.runner import WorkflowRunner
from app.workflows.types import PipelineOutcome, WorkflowContext

__all__ = ["MAX_PROVIDER_ATTEMPTS", "PipelineOutcome", "run_generation_pipeline"]

logger = logging.getLogger(__name__)

# The default template's `route_score` node budget — kept as a module-level
# constant only because it is a convenient single fact for tests and ops
# docs to reference; the actual budget any given job runs with is whatever
# its `route_score` node's `max_attempts` config says.
MAX_PROVIDER_ATTEMPTS: int = RouteScoreConfig.model_fields["max_attempts"].default


def run_generation_pipeline(session: Session, job_id: str) -> PipelineOutcome:
    job = session.get(GenerationJob, job_id)
    if job is None:
        raise LookupError(f"job {job_id} not found")
    set_job_id(job.id)

    if JobStatus(job.status).is_terminal:
        logger.info("job %s already terminal (%s)", job.id, job.status)
        return PipelineOutcome(status=JobStatus(job.status))

    try:
        graph = _resolve_graph(session, job)
        params = dict(job.request_json)
        ctx = WorkflowContext(
            session=session, job=job, prompt=str(params.get("prompt", "")), params=params
        )
        return WorkflowRunner(graph).run(ctx)
    except Exception as exc:
        logger.exception("pipeline crashed for job %s", job.id)
        _fail(session, job, code="INTERNAL_ERROR", message="生成过程出现异常，积分已退回。")
        raise exc from None


def _resolve_graph(session: Session, job: GenerationJob) -> WorkflowGraph:
    """Which graph this job runs, in order of precedence.

    1. The template already pinned on the job (set at submission, or by a
       previous call to this function for a legacy row) — never changes
       mid-flight even if an admin publishes a new version.
    2. The operation's current active template, backfilled onto the job so a
       retry/resume of the same job keeps using it — covers rows created
       before `workflow_template_id` existed.
    3. The code-level default shape, used only when no template has ever been
       published for this operation (a fresh deploy before `make seed`, or a
       test that builds a job without going through the seed script).
    """
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
    return WorkflowGraph.from_dict(default_graph())


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
