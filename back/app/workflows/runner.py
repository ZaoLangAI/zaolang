"""Generic execution engine: walks a `WorkflowGraph`, calling each node's
registered executor and following the edge matching whatever port it returns.

Concurrency note (why fan-out/join branches run sequentially here, not on
real threads or separate Celery subtasks): `state_machine.append_event`
derives `JobEvent.sequence` from `MAX(sequence) + 1` with no row lock, and a
SQLAlchemy `Session` is not thread-safe. Executing branches concurrently
inside one job's run would race on both. Every externally observable
behaviour the design calls for is still delivered: `race` mode stops at the
first branch whose port lands in `JoinConfig.success_ports` (so a slow loser
never blocks the job, it just does not get to finish its own remaining
steps), and `barrier` mode still runs every branch before continuing. What is
given up is wall-clock parallelism between branches — not a contract any
caller of `WorkflowRunner.run` observes.
"""

from __future__ import annotations

import logging
from time import perf_counter

from sqlalchemy import update

from app.domain.jobs import async_tasks, input_requests
from app.domain.jobs import service as jobs_service
from app.domain.jobs import state_machine as sm
from app.domain.system_log import service as system_log
from app.models import AgentRun
from app.models.enums import JobStatus, SystemLogLevel, SystemLogSource
from app.workflows import registry
from app.workflows.graph import (
    HARD_MAX_NODE_VISITS,
    WorkflowEdge,
    WorkflowGraph,
    WorkflowNode,
)
from app.workflows.types import NodeResult, PipelineOutcome, WorkflowContext

logger = logging.getLogger(__name__)


class _EngineError(Exception):
    def __init__(self, code: str, node_id: str, port: str | None = None) -> None:
        super().__init__(f"{code} at {node_id}:{port}")
        self.code = code
        self.node_id = node_id
        self.port = port


class WorkflowRunner:
    """One instance runs one job through one graph."""

    def __init__(self, graph: WorkflowGraph) -> None:
        self._graph = graph
        self._node_map = graph.node_map
        self._entry_id = _entry_node_id(graph)

    def node(self, node_id: str) -> WorkflowNode | None:
        """One node of the graph, for a caller resuming a suspended run that
        needs to know how the node was configured."""
        return self._node_map.get(node_id)

    def run(self, ctx: WorkflowContext) -> PipelineOutcome:
        if not ctx.dry_run and ctx.job.status == JobStatus.CREATED:
            ctx.job = sm.transition(ctx.session, ctx.job.id, JobStatus.QUEUED)
        return self._walk(ctx, self._entry_id, {})

    def resume(self, ctx: WorkflowContext, *, node_id: str, port: str) -> PipelineOutcome:
        """Continues a suspended walk from the node that handed work outside.

        Called by `app.workers.tasks.poll_async_provider_tasks` once the
        external task settled. The node itself is *not* re-executed — it
        already did its work — so this starts from its outgoing `port`.

        Visit counts start fresh: the loop limit exists to stop a graph
        cycling forever inside one run, and the budget that actually governs
        retries (`route_score.max_attempts`) is restored from the checkpoint
        instead.
        """
        visits: dict[str, int] = {}
        try:
            next_id = self._next_node(node_id, port)
        except _EngineError as exc:
            return self._engine_failure(ctx, code=exc.code, node_id=exc.node_id, port=exc.port)
        return self._walk(ctx, next_id, visits)

    def _walk(
        self, ctx: WorkflowContext, start_node_id: str, visits: dict[str, int]
    ) -> PipelineOutcome:
        current = start_node_id
        try:
            while True:
                node = self._node_map[current]
                result = self._execute_node(ctx, current, node.type, visits)
                if result.terminal is not None:
                    return result.terminal
                if result.suspend:
                    return self._suspend(ctx, node_id=current, result=result)

                out_edges = self._graph.edges_from(current, result.port)
                edges = [e for e in out_edges if e.kind != "parallel"]
                parallel = [e for e in out_edges if e.kind == "parallel"]

                if parallel:
                    current, terminal = self._run_parallel_branches(ctx, parallel, visits)
                    if terminal is not None:
                        return terminal
                    continue

                if not edges:
                    raise _EngineError("WORKFLOW_MISCONFIGURED", current, result.port)
                current = edges[0].to_node
        except _EngineError as exc:
            # A broken graph (bad wiring, unknown node type) is a business-
            # level failure an admin can fix by republishing — handled here,
            # not re-raised. An *unexpected* exception (a genuine crash) is
            # deliberately left to propagate: the caller (`run_generation_pipeline`)
            # is the one place that marks the job failed for a real crash and
            # re-raises for Celery's retry, and that contract must stay in one
            # place, not duplicated here.
            return self._engine_failure(ctx, code=exc.code, node_id=exc.node_id, port=exc.port)

    def _next_node(self, node_id: str, port: str) -> str:
        edges = [e for e in self._graph.edges_from(node_id, port) if e.kind != "parallel"]
        if not edges:
            raise _EngineError("WORKFLOW_MISCONFIGURED", node_id, port)
        return edges[0].to_node

    def _suspend(
        self, ctx: WorkflowContext, *, node_id: str, result: NodeResult
    ) -> PipelineOutcome:
        """Parks the job and stops, on whichever of two things it is waiting for.

        Not a terminal outcome: nothing settles, and the reservation stays
        reserved. What makes this safe is the row written here — without it
        the job would sit with nothing left to advance it, and only
        `expire_stale_jobs` (or, for the input-request case,
        `expire_stale_input_requests`) would eventually release the credits.

        `checkpoint["kind"]` is the discriminator between the two suspensions
        the engine knows: `"provider"` (`_provider_checkpoint`) leaves the job
        `RUNNING` for the scheduler to poll, `"input_request"`
        (`_input_checkpoint`) moves it to `AWAITING_INPUT` for its author to
        answer. Anything else defaults to the provider path, matching every
        checkpoint written before this discriminator existed.
        """
        checkpoint = result.checkpoint or {}
        if ctx.dry_run:
            # A sandbox run has no real job to attach a task row to, and no
            # scheduler or author will ever come back for it.
            return PipelineOutcome(status=JobStatus.RUNNING)

        if checkpoint.get("kind") == "input_request":
            input_requests.suspend(
                ctx.session, job_id=ctx.job.id, node_id=node_id, checkpoint=checkpoint
            )
            ctx.job = sm.transition(ctx.session, ctx.job.id, JobStatus.AWAITING_INPUT)
            ctx.session.commit()
            logger.info(
                "job %s suspended at node %s awaiting the author's answer", ctx.job.id, node_id
            )
            return PipelineOutcome(status=JobStatus.AWAITING_INPUT)

        async_tasks.suspend(ctx.session, job_id=ctx.job.id, node_id=node_id, checkpoint=checkpoint)
        ctx.session.commit()
        logger.info("job %s suspended at node %s awaiting an external task", ctx.job.id, node_id)
        return PipelineOutcome(status=JobStatus.RUNNING)

    def _execute_node(
        self, ctx: WorkflowContext, node_id: str, node_type: str, visits: dict[str, int]
    ) -> NodeResult:
        visits[node_id] = visits.get(node_id, 0) + 1
        if visits[node_id] > HARD_MAX_NODE_VISITS:
            raise _EngineError("WORKFLOW_LOOP_LIMIT", node_id)

        spec = registry.NODE_TYPES.get(node_type)
        if spec is None:
            raise _EngineError("WORKFLOW_UNKNOWN_NODE_TYPE", node_id)

        node = self._node_map[node_id]
        config = spec.config_schema.model_validate(node.config or {})
        ctx.state["_current_node_id"] = node_id
        previous_agent_run_id = ctx.state.get("_last_agent_run_id")
        started = perf_counter()
        result = spec.executor(ctx, config)
        elapsed_ms = int((perf_counter() - started) * 1000)
        self._tag_agent_run_node(ctx, node_id=node_id, previous_agent_run_id=previous_agent_run_id)
        self._record_trace(
            ctx, node_id=node_id, node_type=node_type, result=result, duration_ms=elapsed_ms
        )
        return result

    @staticmethod
    def _tag_agent_run_node(
        ctx: WorkflowContext, *, node_id: str, previous_agent_run_id: str | None
    ) -> None:
        """Stamps the `AgentRun` this node's executor just produced with its id.

        `run_agent` has no notion of graph nodes; `_last_agent_run_id` is the
        hook an executor leaves in `ctx.state` after calling it. Compared
        against its value before this node ran, so a node that did not call
        an agent leaves an earlier node's run alone. `AgentRun` rows are
        written unconditionally (including in a dry run), so this is too.
        """
        current = ctx.state.get("_last_agent_run_id")
        if current is None or current == previous_agent_run_id:
            return
        ctx.session.execute(update(AgentRun).where(AgentRun.id == current).values(node_id=node_id))

    def _run_parallel_branches(
        self, ctx: WorkflowContext, parallel_edges: list[WorkflowEdge], visits: dict[str, int]
    ) -> tuple[str, PipelineOutcome | None]:
        """Runs every parallel branch up to (not including) its join node.

        Returns `(join_node_id, None)` to continue the main loop at the join,
        or `(current_node_id, outcome)` if a branch produced a terminal
        outcome — cancellation being the only such case today.
        """
        branch_results: list[NodeResult] = []
        join_node_id: str | None = None

        for edge in parallel_edges:
            node_id = edge.to_node
            last_result: NodeResult | None = None
            while True:
                node_type = self._node_map[node_id].type
                if node_type == "join":
                    if join_node_id is not None and join_node_id != node_id:
                        raise _EngineError("WORKFLOW_MISCONFIGURED", node_id, "join_mismatch")
                    join_node_id = node_id
                    break

                last_result = self._execute_node(ctx, node_id, node_type, visits)
                if last_result.terminal is not None:
                    return node_id, last_result.terminal

                next_edges = [
                    e
                    for e in self._graph.edges_from(node_id, last_result.port)
                    if e.kind != "parallel"
                ]
                if not next_edges:
                    raise _EngineError("WORKFLOW_MISCONFIGURED", node_id, last_result.port)
                node_id = next_edges[0].to_node
            branch_results.append(last_result or NodeResult(port="ok"))

        # The join node itself consumes this via `execute_join`.
        ctx.state["_branch_results"] = branch_results
        assert join_node_id is not None
        return join_node_id, None

    def _engine_failure(
        self, ctx: WorkflowContext, *, code: str, node_id: str, port: str | None = None
    ) -> PipelineOutcome:
        logger.error(
            "workflow engine failure job=%s node=%s port=%s code=%s",
            ctx.job.id,
            node_id,
            port,
            code,
        )
        # Deliberately never a `JobEvent` — its `public_message` is scrubbed
        # for the C-end caller, and "graph misconfigured" / "unknown node
        # type" / "cycle limit exceeded" are internal template-authoring bugs,
        # not something a user retry can fix. This is the only durable trace
        # of *which node* and *why*.
        system_log.emit(
            source=SystemLogSource.PIPELINE,
            event="workflow_engine_failure",
            message=f"node={node_id} port={port} code={code}",
            dedup_key=f"job:{ctx.job.id}:{node_id}",
            level=SystemLogLevel.ERROR,
            job_id=ctx.job.id,
            details={"node_id": node_id, "port": port, "code": code},
        )
        if ctx.dry_run:
            return PipelineOutcome(status=JobStatus.FAILED, failure_code=code)
        try:
            jobs_service.settle_release(ctx.session, ctx.job, reason=code)
        except Exception:
            logger.exception(
                "failed to release credits during engine failure for job %s", ctx.job.id
            )
        try:
            sm.transition(
                ctx.session,
                ctx.job.id,
                JobStatus.FAILED,
                failure_code=code,
                failure_message="生成过程出现异常，积分已退回。",
            )
        except Exception:
            logger.exception("failed to mark job %s failed during engine failure", ctx.job.id)
        return PipelineOutcome(status=JobStatus.FAILED, failure_code=code)

    @staticmethod
    def _record_trace(
        ctx: WorkflowContext,
        *,
        node_id: str,
        node_type: str,
        result: NodeResult,
        duration_ms: int,
    ) -> None:
        trace: list[dict[str, object]] = ctx.state.setdefault("_trace", [])
        trace.append(
            {
                "node_id": node_id,
                "node_type": node_type,
                "port": result.port,
                "agent_run_id": ctx.state.get("_last_agent_run_id"),
                "duration_ms": duration_ms,
                "summary": result.summary,
            }
        )


def _entry_node_id(graph: WorkflowGraph) -> str:
    incoming = {e.to_node for e in graph.edges}
    entries = [n.id for n in graph.nodes if n.id not in incoming]
    if len(entries) != 1:
        raise ValueError(f"graph must have exactly one entry node, found {entries}")
    return entries[0]
