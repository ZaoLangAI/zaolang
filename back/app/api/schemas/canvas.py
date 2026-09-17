"""Infinite-canvas request/response models.

Card `data` payloads stay untyped `dict`s on the wire on purpose: node kinds
and what each one renders are a presentation concern that will churn as card
types are added, and pinning them into the API contract would turn every new
card type into an OpenAPI change. The service layer still enforces the
structural invariants that matter — known kind, resolvable edges, integer
coordinates in range, size caps.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from pydantic import Field

from app.api.schemas.common import ApiModel


class CanvasProjectCreateRequest(ApiModel):
    title: str = Field(min_length=1, max_length=200)
    # Present = drama mode (bound to that series), absent = free sandbox.
    series_id: str | None = Field(default=None, max_length=40)


class CanvasProjectUpdateRequest(ApiModel):
    """Project metadata only.

    The graph is written through `POST /canvas-projects/{id}/graph-ops`, which
    is also where the only compare-and-set in this feature lives. There is no
    `expected_revision` here: a title and a camera position are not worth a 409.
    """

    title: str | None = Field(default=None, min_length=1, max_length=200)
    viewport: dict[str, Any] | None = None


# --------------------------------------------------------------------------
# Graph
# --------------------------------------------------------------------------


class CanvasPosition(ApiModel):
    x: int
    y: int


class CanvasSize(ApiModel):
    width: int
    height: int


class CanvasNodeResponse(ApiModel):
    id: str
    kind: str
    position: CanvasPosition
    size: CanvasSize | None = None
    z_index: int = 0
    binding: dict[str, Any] | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    # `user` or `agent`. Drives a badge; never an access rule.
    origin: str = "user"
    # The compare-and-set token for this one card. Echo it back in a
    # `node.update` / `node.delete` op.
    revision: int = 1


class CanvasEdgeResponse(ApiModel):
    id: str
    source: str
    target: str
    source_handle: str | None = None
    target_handle: str | None = None
    kind: str = "link"


class CanvasGraphOpRequest(ApiModel):
    """One operation in a batch.

    `op_id` is the client's own idempotency handle: it comes back in `applied`
    or in `conflicts` so a queued flush can be reconciled without matching on
    position. The optional fields are read per `kind`; a field left out of a
    `node.update` is left alone rather than cleared, which is what lets a drag
    send position without resending the whole card.
    """

    op_id: str = Field(max_length=64)
    kind: Literal["node.create", "node.update", "node.delete", "edge.create", "edge.delete"]
    node: dict[str, Any] | None = None
    node_id: str | None = Field(default=None, max_length=40)
    expected_revision: int | None = None
    position: CanvasPosition | None = None
    size: CanvasSize | None = None
    z_index: int | None = None
    binding: dict[str, Any] | None = None
    data: dict[str, Any] | None = None
    edge: dict[str, Any] | None = None
    edge_id: str | None = Field(default=None, max_length=40)


class CanvasGraphOpsRequest(ApiModel):
    """A batch of operations, plus where the client thinks it is.

    `base_seq` is not a lock — it is a read cursor. The response returns every
    change after it, so one round trip both writes and catches the client up.
    """

    base_seq: int = Field(default=0, ge=0)
    ops: list[CanvasGraphOpRequest] = Field(default_factory=list, max_length=200)


class CanvasOpConflictResponse(ApiModel):
    """One op that did not apply.

    A conflict is not an error: the rest of the batch still applied, and the
    client resolves this one by adopting the server row carried in `changes`.
    """

    op_id: str
    entity_id: str
    # `stale_revision` — the card moved under this op. `missing` — it is gone.
    reason: str


class CanvasChangeResponse(ApiModel):
    seq: int
    entity_type: str
    entity_id: str
    action: str
    actor: str
    # The row as it now stands. Empty for a delete — there is nothing to carry.
    payload: dict[str, Any] = Field(default_factory=dict)


class CanvasGraphOpsResponse(ApiModel):
    change_seq: int
    applied: list[str] = Field(default_factory=list)
    conflicts: list[CanvasOpConflictResponse] = Field(default_factory=list)
    # Everything after the request's `base_seq`, including this batch's own
    # writes — so a client that fell behind converges without a second call.
    changes: list[CanvasChangeResponse] = Field(default_factory=list)
    # Stated rather than left for the client to infer. `changes` can legitimately
    # be empty (a batch where every op conflicted), and sequence numbers are
    # monotonic but not dense, so there is no reliable way to tell "nothing to
    # report" from "your cursor is unreconstructable" by looking at the numbers.
    # The write still applied; only the catch-up is unavailable, so the client
    # reloads to converge rather than treating this as a failure.
    gap: bool = False


class CanvasChangesResponse(ApiModel):
    change_seq: int
    changes: list[CanvasChangeResponse] = Field(default_factory=list)
    # The requested cursor can no longer be reconstructed. Reload the canvas;
    # do not apply `changes`, which is empty and would look like "no news".
    gap: bool = False


# --------------------------------------------------------------------------
# Projects
# --------------------------------------------------------------------------


class CanvasProjectSummaryResponse(ApiModel):
    id: str
    title: str
    series_id: str | None = None
    # Derived from `series_id` rather than stored, so the two can't disagree.
    mode: str
    change_seq: int
    viewer_role: str
    node_count: int = 0
    created_at: dt.datetime
    updated_at: dt.datetime


class CanvasProjectWriteResponse(ApiModel):
    """What a metadata write returns.

    Deliberately carries neither the graph nor the `snapshot`: a title or
    viewport change touches no card and no domain object, so returning either
    would be a copy of what the client already holds.
    """

    id: str
    title: str
    series_id: str | None = None
    mode: str
    change_seq: int
    viewer_role: str
    viewport: dict[str, Any] = Field(default_factory=dict)
    created_at: dt.datetime
    updated_at: dt.datetime


class CanvasProjectResponse(ApiModel):
    id: str
    title: str
    series_id: str | None = None
    mode: str
    change_seq: int
    viewer_role: str
    viewport: dict[str, Any] = Field(default_factory=dict)
    nodes: list[CanvasNodeResponse] = Field(default_factory=list)
    edges: list[CanvasEdgeResponse] = Field(default_factory=list)
    # Batched domain hydration — mostly empty for a free canvas, which has no
    # domain objects behind its cards.
    snapshot: dict[str, Any] = Field(default_factory=dict)
    created_at: dt.datetime
    updated_at: dt.datetime


# --------------------------------------------------------------------------
# Agent
# --------------------------------------------------------------------------


class CanvasAgentRunCreateRequest(ApiModel):
    """Start a planning turn on one card.

    `quality_tier` is a *ceiling*, not an instruction: the planner may choose
    something cheaper for a draft, never something dearer.

    There is no auto-submit field. Planning never spends credits; only
    `POST /canvas-agent-runs/{id}/confirm` does, and that is deliberate —
    spending a balance without a confirming tap is what generates refund
    tickets.
    """

    agent_node_id: str = Field(max_length=40)
    goal: str = Field(min_length=1, max_length=2000)
    quality_tier: str = Field(default="standard", max_length=24)
    max_tasks: int = Field(default=2, ge=1, le=4)
    max_credits: int | None = Field(default=None, ge=0)


class CanvasWorkflowRunCreateRequest(ApiModel):
    """Run a creation workflow — a `CreationSkill` carrying a variable form.

    `answers` is keyed by the question `id` declared in the skill's
    `params_json["variables"]`. There is no `operation` field: the recipe was
    written for one modality and reads it off the skill, because letting a
    caller choose would submit a video job carrying a still-frame recipe.

    Like a planned run this stops at `awaiting_confirm` — the form is the step
    before confirmation, and `POST /canvas-agent-runs/{id}/confirm` is still
    the only thing that spends credits.
    """

    skill_id: str = Field(max_length=40)
    node_id: str = Field(max_length=40)
    answers: dict[str, Any] = Field(default_factory=dict)
    quality_tier: str = Field(default="standard", max_length=24)
    max_credits: int | None = Field(default=None, ge=0)


class CanvasAgentTaskResponse(ApiModel):
    id: str
    ordinal: int
    operation: str
    quality_tier: str
    prompt: str = ""
    status: str
    generation_job_id: str | None = None
    # Where the result will land, so the UI can show the slot before it fills.
    drop: CanvasPosition
    result_node_id: str | None = None
    failure_message: str | None = None


class CanvasAgentRunResponse(ApiModel):
    id: str
    canvas_id: str
    status: str
    # `agent` for a planned run, `workflow` for one expanded from a skill
    # template. A column rather than a guess from `model is None`, so the
    # workbench can label a run without inferring it.
    origin: str = "agent"
    goal: str
    summary: str = ""
    agent_node_id: str | None = None
    # Exactly the cards the planner was shown, so a run is auditable rather
    # than a black box that spent money.
    context_node_ids: list[str] = Field(default_factory=list)
    quoted_credits: int = 0
    model: str | None = None
    failure_code: str | None = None
    failure_message: str | None = None
    tasks: list[CanvasAgentTaskResponse] = Field(default_factory=list)
    created_at: dt.datetime
    updated_at: dt.datetime
