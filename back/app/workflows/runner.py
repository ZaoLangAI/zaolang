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

from app.domain.jobs import service as jobs_service
from app.domain.jobs import state_machine as sm
from app.models.enums import JobStatus
from app.workflows import registry
from app.workflows.graph import HARD_MAX_NODE_VISITS, WorkflowEdge, WorkflowGraph
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

    def run(self, ctx: WorkflowContext) -> PipelineOutcome:
        if not ctx.dry_run and ctx.job.status == JobStatus.CREATED:
            ctx.job = sm.transition(ctx.session, ctx.job.id, JobStatus.QUEUED)

        visits: dict[str, int] = {}
        current = self._entry_id
        try:
            while True:
                node = self._node_map[current]
                result = self._execute_node(ctx, current, node.type, visits)
                if result.terminal is not None:
                    return result.terminal

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
        result = spec.executor(ctx, config)
        self._record_trace(ctx, node_id=node_id, node_type=node_type, result=result)
        return result

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
        ctx: WorkflowContext, *, node_id: str, node_type: str, result: NodeResult
    ) -> None:
        trace: list[dict[str, object]] = ctx.state.setdefault("_trace", [])
        trace.append(
            {
                "node_id": node_id,
                "node_type": node_type,
                "port": result.port,
                "agent_run_id": ctx.state.get("_last_agent_run_id"),
            }
        )


def _entry_node_id(graph: WorkflowGraph) -> str:
    incoming = {e.to_node for e in graph.edges}
    entries = [n.id for n in graph.nodes if n.id not in incoming]
    if len(entries) != 1:
        raise ValueError(f"graph must have exactly one entry node, found {entries}")
    return entries[0]
