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
from app.models.enums import JobStatus


@dataclass(slots=True)
class PipelineOutcome:
    status: JobStatus
    failure_code: str | None = None
    asset_id: str | None = None


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
    state: dict[str, Any] = field(default_factory=dict)

    @property
    def agent_job_id(self) -> str | None:
        """The job id to attach to an `AgentRun`, or `None` in a dry run.

        A dry run's `job` is a transient object never inserted into the
        database, so writing its id onto `AgentRun.job_id` — a real foreign
        key — would fail the insert.
        """
        return None if self.dry_run else self.job.id


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
    in the editor's dry-run trace. Purely diagnostic: nothing branches on it,
    and a node with nothing worth saying leaves it `None`. It must never
    carry anything the C-end user is not allowed to see, since the ops
    console renders it verbatim.
    """

    port: str
    terminal: PipelineOutcome | None = None
    suspend: bool = False
    checkpoint: dict[str, Any] | None = None
    summary: str | None = None
