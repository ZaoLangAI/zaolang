"""Shared runtime types for the workflow engine.

Split out from `runner.py`/`nodes.py` so `app.workers.pipeline` can import
`PipelineOutcome` without creating an import cycle (pipeline -> workflows ->
pipeline).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.models import GenerationJob
from app.models.enums import JobOrigin, JobStatus

# Stashed by `nodes._emit(..., publish=False)` so `WorkflowRunner._suspend`
# can commit the `AWAITING_INPUT` JobEvent together with the input-request
# row and the status transition, then Redis-publish.
DEFERRED_JOB_EVENT_STATE_KEY = "_deferred_job_event"


@dataclass(slots=True)
class PipelineOutcome:
    status: JobStatus
    failure_code: str | None = None
    asset_id: str | None = None
    # Every asset produced, in generation order — `asset_id` above is always
    # `asset_ids[0]` when this is set. `None` for the overwhelming majority
    # of jobs that only ever make one asset; see `GenerationJob.output_asset_ids_json`.
    asset_ids: list[str] | None = None
    # `video_analysis`'s own output: a structured text breakdown instead of
    # an asset. Mutually exclusive with `asset_id`/`asset_ids` — this
    # operation never registers an `Asset`. Written to
    # `GenerationJob.analysis_result_json` by `app.workers.pipeline`.
    result_json: dict[str, Any] | None = None


@dataclass(slots=True)
class WorkflowContext:
    """Mutable state threaded through one job's walk across the graph.

    `state` is scratch space node executors use to hand data to their
    downstream neighbours (e.g. `route_score` leaves its `RoutingDecision`
    here for `provider_generate` to pick up) — it is never persisted itself,
    only what individual executors explicitly write to the database is.
    """

    session: Session
    job: GenerationJob
    prompt: str
    params: dict[str, Any]
    dry_run: bool = False
    # When set with `dry_run`, `provider_generate` calls the real media
    # provider instead of stubbing. Still never creates a `GenerationJob`,
    # reserves credits, or writes a `ProviderAttempt`.
    live_provider: bool = False
    state: dict[str, Any] = field(default_factory=dict)

    @property
    def agent_job_id(self) -> str | None:
        """The job id to attach to an `AgentRun`, or `None` in a dry run.

        A dry run's `job` is a transient object never inserted into the
        database, so writing its id onto `AgentRun.job_id` — a real foreign
        key — would fail the insert.
        """
        return None if self.dry_run else self.job.id

    @property
    def is_sandbox(self) -> bool:
        """A real persisted try-it from the workflow editor (not a unit-test dry run)."""
        return (not self.dry_run) and self.job.origin == JobOrigin.SANDBOX


@dataclass(slots=True)
class NodeResult:
    """What one node executor hands back to the runner.

    `port` selects which outgoing edge to follow next. `terminal`, when set,
    tells the runner to stop immediately and return this outcome regardless
    of the graph — used only for the cancellation path, which (per design) is
    built into `provider_generate` rather than modelled as its own node type.

    `suspend` stops the walk *without* finishing the job: the node handed
    work to an external system that will take minutes, and
    `app.workers.tasks.poll_async_provider_tasks` resumes from this node once
    it settles. `checkpoint` is everything the resumed run needs that lives
    only in `ctx.state`, and must be JSON-safe — it goes to the database.

    `summary` is one human-readable line about what this step decided, shown
    in the ops console and the sandbox inspector. Purely diagnostic: nothing branches on it,
    and a node with nothing worth saying leaves it `None`. It must never
    carry anything the C-end user is not allowed to see, since the ops
    console renders it verbatim.
    """

    port: str
    terminal: PipelineOutcome | None = None
    suspend: bool = False
    checkpoint: dict[str, Any] | None = None
    summary: str | None = None
