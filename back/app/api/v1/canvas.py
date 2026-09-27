"""Infinite-canvas projects — project CRUD, graph writes, and catch-up reads.

Domain writes stay absent: episodes, scripts and drafts keep their own routes.
What lives here is the canvas' own content and layout.

The write path is `POST /canvas-projects/{id}/graph-ops`, and it is deliberately
not a whole-document PUT. See `app/domain/canvas/graph_service.py` for why —
briefly, a worker landing a generated card and a browser autosaving a drag must
both succeed, and a document-shaped write gives them one cell to fight over.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from typing import Annotated, Any

from fastapi import APIRouter, Header, Query, Response, status
from fastapi.responses import StreamingResponse

from app.api import idempotency, sse_quota
from app.api.deps import CurrentUser, DbSession, IdempotencyKey
from app.api.schemas.canvas import (
    CanvasAgentRunCreateRequest,
    CanvasAgentRunResponse,
    CanvasAgentTaskResponse,
    CanvasChangeResponse,
    CanvasChangesResponse,
    CanvasEdgeResponse,
    CanvasGraphOpsRequest,
    CanvasGraphOpsResponse,
    CanvasNodeResponse,
    CanvasOpConflictResponse,
    CanvasPosition,
    CanvasProjectCreateRequest,
    CanvasProjectResponse,
    CanvasProjectSummaryResponse,
    CanvasProjectUpdateRequest,
    CanvasProjectWriteResponse,
    CanvasWorkflowRunCreateRequest,
)
from app.domain.canvas import agent_service, graph_service, workflow_service
from app.domain.canvas import service as canvas_service
from app.domain.errors import DomainError
from app.domain.jobs import dispatch as job_dispatch
from app.models import (
    CanvasAgentRun,
    CanvasChange,
    CanvasEdge,
    CanvasNode,
    CanvasProject,
)
from app.realtime import publisher

router = APIRouter(tags=["canvas"])

SSE_HEARTBEAT_SECONDS = 15
SSE_MAX_DURATION_SECONDS = 600


def _mode(project: CanvasProject) -> str:
    return "drama" if project.series_id else "free"


def _viewer_role(project: CanvasProject, user_id: str) -> str:
    """Mirrors `DramaSeriesResponse.viewer_role`. A collaborator may arrange a
    shared series' canvas, but the UI must keep owner-only actions (timeline
    editor, publish, trash, deleting the canvas) hidden for them."""
    return "owner" if project.owner_user_id == user_id else "collaborator"


def _node(node: CanvasNode) -> CanvasNodeResponse:
    return CanvasNodeResponse.model_validate(graph_service.node_payload(node))


def _edge(edge: CanvasEdge) -> CanvasEdgeResponse:
    return CanvasEdgeResponse.model_validate(graph_service.edge_payload(edge))


def _change(change: CanvasChange) -> CanvasChangeResponse:
    return CanvasChangeResponse.model_validate(graph_service.change_payload(change))


def _summary(
    session: DbSession, project: CanvasProject, user_id: str
) -> CanvasProjectSummaryResponse:
    return CanvasProjectSummaryResponse(
        id=project.id,
        title=project.title,
        series_id=project.series_id,
        mode=_mode(project),
        change_seq=project.change_seq,
        viewer_role=_viewer_role(project, user_id),
        node_count=graph_service.node_count(session, project.id),
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


def _detail(session: DbSession, project: CanvasProject, user_id: str) -> CanvasProjectResponse:
    return CanvasProjectResponse(
        id=project.id,
        title=project.title,
        series_id=project.series_id,
        mode=_mode(project),
        change_seq=project.change_seq,
        viewer_role=_viewer_role(project, user_id),
        viewport=project.viewport_json or {},
        nodes=[_node(node) for node in graph_service.read_nodes(session, project.id)],
        edges=[_edge(edge) for edge in graph_service.read_edges(session, project.id)],
        snapshot=canvas_service.domain_snapshot(session, project, viewer_id=user_id),
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


@router.get("/canvas-projects", response_model=list[CanvasProjectSummaryResponse])
def list_canvas_projects(
    user: CurrentUser, session: DbSession
) -> list[CanvasProjectSummaryResponse]:
    projects = canvas_service.list_projects(session, user_id=user.id)
    return [_summary(session, project, user.id) for project in projects]


@router.post(
    "/canvas-projects",
    response_model=CanvasProjectResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_canvas_project(
    payload: CanvasProjectCreateRequest, user: CurrentUser, session: DbSession
) -> CanvasProjectResponse:
    project = canvas_service.create_project(
        session, user_id=user.id, title=payload.title, series_id=payload.series_id
    )
    session.commit()
    session.refresh(project)
    return _detail(session, project, user.id)


@router.get("/canvas-projects/{canvas_id}", response_model=CanvasProjectResponse)
def get_canvas_project(
    canvas_id: str, user: CurrentUser, session: DbSession
) -> CanvasProjectResponse:
    project = canvas_service.get_project(session, user_id=user.id, canvas_id=canvas_id)
    return _detail(session, project, user.id)


@router.patch("/canvas-projects/{canvas_id}", response_model=CanvasProjectWriteResponse)
def update_canvas_project(
    canvas_id: str,
    payload: CanvasProjectUpdateRequest,
    user: CurrentUser,
    session: DbSession,
) -> CanvasProjectWriteResponse:
    project = canvas_service.update_project(
        session,
        user_id=user.id,
        canvas_id=canvas_id,
        title=payload.title,
        viewport=payload.viewport,
    )
    session.commit()
    session.refresh(project)
    return CanvasProjectWriteResponse(
        id=project.id,
        title=project.title,
        series_id=project.series_id,
        mode=_mode(project),
        change_seq=project.change_seq,
        viewer_role=_viewer_role(project, user.id),
        viewport=project.viewport_json or {},
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


@router.post("/canvas-projects/{canvas_id}/graph-ops", response_model=CanvasGraphOpsResponse)
def apply_canvas_graph_ops(
    canvas_id: str,
    payload: CanvasGraphOpsRequest,
    user: CurrentUser,
    session: DbSession,
) -> CanvasGraphOpsResponse:
    """Apply a batch of card/connection operations.

    Returns 200 even when some ops did not apply. A stale op is reported in
    `conflicts` and the rest of the batch still lands — rolling twenty accepted
    drags back because a twenty-first card moved under one of them would lose
    real work to protect nothing.
    """
    project = canvas_service.get_project(session, user_id=user.id, canvas_id=canvas_id)
    result = graph_service.apply_ops(
        session,
        canvas_id=project.id,
        user_id=user.id,
        ops=[op.model_dump(exclude_unset=True) for op in payload.ops],
    )
    # Read the catch-up window inside the same transaction as the write, so the
    # client cannot be handed a `change_seq` it has no changes to explain.
    missed, gap = graph_service.changes_since(session, project.id, since=payload.base_seq)
    # Serialise before committing: the ORM rows expire on commit, and re-reading
    # them would cost a query per change to rebuild what is already in hand.
    written = [graph_service.change_payload(change) for change in result.changes]
    frames = [] if gap else [_change(change) for change in missed]
    session.commit()
    # Only after the commit. Announcing a write that can still roll back would
    # have other windows render a card the database never kept.
    graph_service.publish_changes(project.id, written)
    return CanvasGraphOpsResponse(
        change_seq=result.change_seq,
        applied=result.applied,
        conflicts=[
            CanvasOpConflictResponse(
                op_id=conflict.op_id, entity_id=conflict.entity_id, reason=conflict.reason
            )
            for conflict in result.conflicts
        ],
        # Empty on a gap: an incomplete history applied as if complete is worse
        # than none. `gap` says so outright, because an empty list is also a
        # legitimate outcome (a batch in which every op conflicted).
        changes=frames,
        gap=gap,
    )


@router.get("/canvas-projects/{canvas_id}/changes", response_model=CanvasChangesResponse)
def read_canvas_changes(
    canvas_id: str,
    user: CurrentUser,
    session: DbSession,
    since: int = Query(default=0, ge=0),
) -> CanvasChangesResponse:
    """Non-SSE catch-up. `gap: true` means reload rather than apply."""
    project = canvas_service.get_project(session, user_id=user.id, canvas_id=canvas_id)
    changes, gap = graph_service.changes_since(session, project.id, since=since)
    return CanvasChangesResponse(
        change_seq=project.change_seq,
        changes=[] if gap else [_change(change) for change in changes],
        gap=gap,
    )


@router.get("/canvas-projects/{canvas_id}/events")
def stream_canvas_events(
    canvas_id: str,
    user: CurrentUser,
    session: DbSession,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> StreamingResponse:
    """Live changes for one canvas, resumable by `Last-Event-ID`.

    One connection per open canvas, not one per generation in flight. That is
    the whole reason this exists rather than the client fanning out over
    `GET /generation-jobs/{id}/events`: `sse_quota.MAX_CONCURRENT_STREAMS_PER_USER`
    is 8, so a four-task Agent run opened in two tabs would consume a user's
    entire budget and starve their notification stream. It also gives multiple
    tabs and co-creators one convergence path instead of several.

    Unlike the job stream this has no terminal state — a canvas is never
    "finished" — so it runs until `SSE_MAX_DURATION_SECONDS` and the client
    reconnects with its cursor.
    """
    project = canvas_service.get_project(session, user_id=user.id, canvas_id=canvas_id)
    after = _parse_last_event_id(last_event_id)
    stream_slot = sse_quota.reserve("canvas_events", user.id)

    # Read the backfill while the request session is still open: it is a bounded
    # query, and doing it inside the generator would hold a second connection
    # for the life of the stream.
    missed, gap = graph_service.changes_since(session, project.id, since=after)
    backfill: list[dict[str, Any]] = [graph_service.change_payload(change) for change in missed]
    current_seq = project.change_seq
    # Everything the generator needs, as plain values. Nothing below may touch
    # the session or an ORM object again.
    canvas_pk = project.id
    viewer_id = user.id

    # Release the request transaction *now*.
    #
    # FastAPI tears a dependency down only after the response completes, so for
    # a `StreamingResponse` the session would otherwise sit `idle in
    # transaction` for the whole stream. A job stream gets away with it because
    # it ends when the job does; a canvas is never finished, so every open
    # canvas would pin a connection — and an open transaction at that, which
    # blocks DDL and holds back vacuum — for `SSE_MAX_DURATION_SECONDS` at a
    # time, indefinitely. The dependency's own `close()` afterwards is a no-op.
    session.close()

    def generate() -> Iterator[str]:
        started = time.monotonic()
        last_sequence = after

        try:
            if gap:
                # The cursor predates what the feed can reconstruct. Say so and
                # stop: streaming a partial history the client would apply as
                # if complete is the one outcome worse than making it reload.
                yield _sse_gap(current_seq)
                return

            for frame in backfill:
                last_sequence = int(frame["seq"])
                yield _sse(last_sequence, frame)

            # The client now holds everything up to `last_sequence` and is
            # live. Without this it cannot tell "caught up, waiting" from
            # "still replaying" — which matters because the two call for
            # different UI, and because a client that starts applying live
            # frames mid-backfill can apply them out of order.
            yield _sse_synced(last_sequence)

            last_heartbeat = time.monotonic()
            for frame in publisher.subscribe_canvas(canvas_pk):
                if time.monotonic() - started > SSE_MAX_DURATION_SECONDS:
                    break
                if not frame:
                    if time.monotonic() - last_heartbeat > SSE_HEARTBEAT_SECONDS:
                        last_heartbeat = time.monotonic()
                        sse_quota.touch("canvas_events", viewer_id, stream_slot)
                        yield ": heartbeat\n\n"
                    continue

                sequence = int(frame.get("seq", 0))
                # Pub/sub can redeliver something the backfill already carried,
                # and frames from two writers can arrive out of order.
                if sequence <= last_sequence:
                    continue
                last_sequence = sequence
                yield _sse(sequence, frame)
        finally:
            sse_quota.release("canvas_events", viewer_id, stream_slot)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "cache-control": "no-cache",
            "connection": "keep-alive",
            "x-accel-buffering": "no",
        },
    )


def _sse(event_id: int, payload: dict[str, Any]) -> str:
    return f"id: {event_id}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _sse_synced(change_seq: int) -> str:
    """Marks the end of the backfill. Carries no `id:` — it is a position the
    client already has, not a change to resume from."""
    body = json.dumps({"change_seq": change_seq}, ensure_ascii=False)
    return f"event: synced\ndata: {body}\n\n"


def _sse_gap(change_seq: int) -> str:
    """A named event rather than a change frame, so a client cannot mistake it
    for graph content. Carries no `id:` — there is no cursor worth resuming
    from, which is the point."""
    body = json.dumps({"change_seq": change_seq}, ensure_ascii=False)
    return f"event: gap\ndata: {body}\n\n"


def _parse_last_event_id(value: str | None) -> int:
    if not value:
        return 0
    try:
        return max(0, int(value))
    except ValueError:
        return 0


@router.delete("/canvas-projects/{canvas_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_canvas_project(canvas_id: str, user: CurrentUser, session: DbSession) -> Response:
    canvas_service.delete_project(session, user_id=user.id, canvas_id=canvas_id)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/drama-series/{series_id}/canvas", response_model=CanvasProjectResponse)
def get_series_canvas(
    series_id: str, user: CurrentUser, session: DbSession
) -> CanvasProjectResponse:
    """Resolve-or-create, so the series page's "画布视图" button is one click
    rather than a create-then-open dance."""
    project = canvas_service.get_or_create_for_series(session, user_id=user.id, series_id=series_id)
    session.commit()
    session.refresh(project)
    return _detail(session, project, user.id)


# --------------------------------------------------------------------------
# Agent
# --------------------------------------------------------------------------


def _agent_run_response(session: DbSession, run: CanvasAgentRun) -> CanvasAgentRunResponse:
    tasks = agent_service.tasks_for(session, run.id)
    plan = run.plan_json or {}
    return CanvasAgentRunResponse(
        id=run.id,
        canvas_id=run.canvas_id,
        status=run.status,
        origin=run.origin,
        goal=run.goal,
        summary=str(plan.get("summary") or ""),
        agent_node_id=run.agent_node_id,
        context_node_ids=list(run.context_node_ids_json or []),
        quoted_credits=run.quoted_credits,
        model=run.model,
        failure_code=run.failure_code,
        failure_message=run.failure_message,
        tasks=[
            CanvasAgentTaskResponse(
                id=task.id,
                ordinal=task.ordinal,
                operation=task.operation,
                quality_tier=task.quality_tier,
                prompt=str((task.request_json or {}).get("prompt") or ""),
                status=task.status,
                generation_job_id=task.generation_job_id,
                drop=CanvasPosition(x=task.drop_x, y=task.drop_y),
                result_node_id=task.result_node_id,
                failure_message=task.failure_message,
            )
            for task in tasks
        ],
        created_at=run.created_at,
        updated_at=run.updated_at,
    )


@router.post("/canvas-projects/{canvas_id}/agent-runs", status_code=202)
def create_canvas_agent_run(
    canvas_id: str,
    payload: CanvasAgentRunCreateRequest,
    user: CurrentUser,
    session: DbSession,
) -> StreamingResponse:
    """Plan a generation from one card and the cards feeding it.

    202 + `text/event-stream`, the same envelope script turns and the editor
    planner use (`thinking` / `delta` / `complete` / `error`). The run is
    written only once the stream has drained — a plan that never completes
    should leave no row behind.
    """
    from app.api.agent_sse import SSE_HEADERS, iter_agent_sse
    from app.db import session_scope

    project, node, digest, node_ids, chunks, finalize = agent_service.prepare_plan(
        session,
        user_id=user.id,
        canvas_id=canvas_id,
        agent_node_id=payload.agent_node_id,
        goal=payload.goal,
        quality_tier=payload.quality_tier,
        max_tasks=payload.max_tasks,
    )
    # Plain values: the generator runs after this request's session is gone.
    origin = (node.position_x, node.position_y)
    canvas_pk = project.id
    node_pk = node.id

    def generate() -> Iterator[str]:
        def _finish() -> CanvasAgentRunResponse:
            # A fresh session, so the resolving one can close before the LLM
            # stream finishes — same reason `create_edit_plan` does it.
            with session_scope() as persist:
                outcome = finalize(persist)
                run = agent_service.persist_run(
                    persist,
                    user_id=user.id,
                    canvas_id=canvas_pk,
                    agent_node_id=node_pk,
                    goal=payload.goal,
                    quality_tier=payload.quality_tier,
                    max_tasks=payload.max_tasks,
                    digest=digest,
                    context_node_ids=node_ids,
                    origin=origin,
                    outcome=outcome,
                )
                if payload.max_credits is not None:
                    run.max_credits = payload.max_credits
                response = _agent_run_response(persist, run)
                persist.commit()
                return response

        yield from iter_agent_sse(chunks, _finish, lambda run: run.model_dump(mode="json"))

    return StreamingResponse(
        generate(),
        status_code=202,
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


@router.post(
    "/canvas-projects/{canvas_id}/workflow-runs",
    response_model=CanvasAgentRunResponse,
    status_code=201,
)
def create_canvas_workflow_run(
    canvas_id: str,
    payload: CanvasWorkflowRunCreateRequest,
    user: CurrentUser,
    session: DbSession,
) -> CanvasAgentRunResponse:
    """Expand a workflow skill into a priced, unconfirmed run.

    Plain JSON rather than the planner's SSE: there is no model call here, so
    there is nothing to stream. The run it produces is the same
    `CanvasAgentRun` the planner produces, and goes on through the same
    `/confirm` and `/cancel`.
    """
    run = workflow_service.start_run(
        session,
        user_id=user.id,
        canvas_id=canvas_id,
        skill_id=payload.skill_id,
        node_id=payload.node_id,
        answers=payload.answers,
        quality_tier=payload.quality_tier,
        max_credits=payload.max_credits,
    )
    response = _agent_run_response(session, run)
    session.commit()
    return response


CONFIRM_AGENT_RUN_ENDPOINT = "POST /v1/canvas-agent-runs/{run_id}/confirm"


@router.post("/canvas-agent-runs/{run_id}/confirm", response_model=CanvasAgentRunResponse)
def confirm_canvas_agent_run(
    run_id: str,
    user: CurrentUser,
    session: DbSession,
    idempotency_key: IdempotencyKey,
) -> CanvasAgentRunResponse:
    """Spend the credits and submit the planned jobs.

    The conditional transition in `confirm_run` already stops a second confirm
    from reserving credits twice, but it answers that second call with an
    error. A client retrying after a timeout needs the answer the first call
    got instead — the credits *were* spent — so a keyed retry replays it.
    """
    request_hash = idempotency.hash_request({"run_id": run_id})
    if idempotency_key:
        replay = idempotency.find_replay(
            session,
            user_id=user.id,
            endpoint=CONFIRM_AGENT_RUN_ENDPOINT,
            key=idempotency_key,
            request_hash=request_hash,
        )
        if replay is not None:
            return CanvasAgentRunResponse.model_validate(replay.response_snapshot)

    try:
        run, dispatched = agent_service.confirm_run(session, user_id=user.id, run_id=run_id)
    except DomainError:
        if not idempotency_key:
            raise
        # A retry that arrived while the original was still in flight got past
        # the lookup above, then blocked on the run row until the original
        # committed and lost the transition. The original's record is visible
        # now; answering with it is the whole point of the key.
        session.rollback()
        replay = idempotency.find_replay(
            session,
            user_id=user.id,
            endpoint=CONFIRM_AGENT_RUN_ENDPOINT,
            key=idempotency_key,
            request_hash=request_hash,
        )
        if replay is None:
            raise
        return CanvasAgentRunResponse.model_validate(replay.response_snapshot)
    response = _agent_run_response(session, run)
    if idempotency_key:
        # In the same transaction as the reservation: a committed spend always
        # has its replay, and a rolled-back one never does.
        idempotency.remember(
            session,
            user_id=user.id,
            endpoint=CONFIRM_AGENT_RUN_ENDPOINT,
            key=idempotency_key,
            request_hash=request_hash,
            status_code=200,
            response=response.model_dump(mode="json"),
        )
    session.commit()
    # After the commit, for the same reason canvas changes are: a broker that
    # picks the job up before its row is visible would find nothing.
    #
    # Unconditional, exactly as `jobs.create_job` does it. An earlier version
    # guarded on `status == QUEUED` and therefore never fired at all — `submit`
    # leaves a job at `created`, and the move to `queued` belongs to the worker
    # this call is supposed to be waking up.
    for job in dispatched:
        job_dispatch.enqueue_or_fail(session, job)
    return response


@router.post("/canvas-agent-runs/{run_id}/cancel", response_model=CanvasAgentRunResponse)
def cancel_canvas_agent_run(
    run_id: str, user: CurrentUser, session: DbSession
) -> CanvasAgentRunResponse:
    run = agent_service.cancel_run(session, user_id=user.id, run_id=run_id)
    response = _agent_run_response(session, run)
    session.commit()
    return response


@router.post(
    "/canvas-agent-tasks/{task_id}/restore-card", response_model=CanvasNodeResponse, status_code=201
)
def restore_canvas_task_card(
    task_id: str, user: CurrentUser, session: DbSession
) -> CanvasNodeResponse:
    """Put a landed result back on the canvas after its card was deleted."""
    node = agent_service.restore_task_card(session, user_id=user.id, task_id=task_id)
    response = _node(node)
    # The new card is announced to other windows by `_queue_frames`'s own
    # `after_commit` listener; nothing to publish by hand here.
    session.commit()
    return response


@router.get("/canvas-agent-runs/{run_id}", response_model=CanvasAgentRunResponse)
def get_canvas_agent_run(
    run_id: str, user: CurrentUser, session: DbSession
) -> CanvasAgentRunResponse:
    run = agent_service.get_run(session, user_id=user.id, run_id=run_id)
    return _agent_run_response(session, run)


@router.get("/canvas-projects/{canvas_id}/agent-runs", response_model=list[CanvasAgentRunResponse])
def list_canvas_agent_runs(
    canvas_id: str, user: CurrentUser, session: DbSession
) -> list[CanvasAgentRunResponse]:
    runs = agent_service.list_runs(session, user_id=user.id, canvas_id=canvas_id)
    return [_agent_run_response(session, run) for run in runs]
