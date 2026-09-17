"""Infinite-canvas projects: a spatial view over creative work, and a place to
create from.

A canvas is a second way to create, alongside the linear script -> shot ->
generate -> edit path. It comes in two modes, distinguished solely by whether
`series_id` is set:

* **Drama mode** (`series_id` set) - cards bind to real domain objects
  (`DramaEpisode`, a script breakpoint, a `CreationSkill`, a `Draft`, a
  `Work`). The canvas and `/create/short`'s dashboard are two views of one
  truth.
* **Free sandbox** (`series_id` NULL) - cards are standalone image / video /
  prompt / note cards. They still stand on real `Asset` / `Draft` rows
  (generation goes through the ordinary pipeline with no `link_episode_id`),
  they just hang off no episode. A card can later be "sent to" an episode,
  which writes an `EpisodeContentLink` - that upgrade path is what keeps a
  free canvas from silently becoming a second, disconnected asset library.

Domain writes keep going through their own routes (`/v1/drama-episodes`,
`/v1/scripts`, `/v1/drafts`); these tables never become a parallel write path
for them. What changed from the first cut of this feature is narrower than
that rule: the canvas now stores *its own* content (cards an Agent produced)
rather than only positions.

**Why rows instead of one `graph_json` blob.** An Agent run submits a real
`GenerationJob`, and minutes later the finished output has to appear as a card.
That write comes from a worker, concurrently with the browser autosaving
layout. With one JSON column both writers are `UPDATE canvas_projects SET
graph_json = ?` - the whole document *is* the granule, so there is no
compare-and-set fine enough to let them both through, and every server write
would collide with every autosave. Splitting into rows makes landing a result
an `INSERT` that by construction cannot collide with a client's `UPDATE` of a
different row. See `app/domain/canvas/graph_service.py` for the three rules
that follow from this.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, id_column
from app.models.enums import (
    CanvasAgentRunOrigin,
    CanvasAgentRunStatus,
    CanvasAgentTaskStatus,
    CanvasNodeOrigin,
)


class CanvasProject(Base, TimestampMixin):
    __tablename__ = "canvas_projects"

    id: Mapped[str] = id_column("cnv")
    # Required even in drama mode: a free canvas has no Series to derive
    # ownership from, so ownership is always stated directly rather than
    # being inferred from whichever mode the row happens to be in.
    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # NULL is the free sandbox; a value is drama mode. Not a separate `mode`
    # column - that would let the two disagree.
    series_id: Mapped[str | None] = mapped_column(
        ForeignKey("series.id", ondelete="CASCADE"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    # Where the camera was left. Per-canvas rather than per-viewer: reopening
    # a canvas and finding it framed the way you left it is worth more than
    # two people disagreeing about the scroll position.
    viewport_json: Mapped[dict[str, Any]] = mapped_column(default=dict, nullable=False)
    # Canvas-scoped monotonic stamp, allocated by `graph_service._next_seq`.
    #
    # NOT a compare-and-set token. The column it replaces (`revision`) was one,
    # and that was the defect: two writers had to fight over a single number
    # and the loser was rejected. Here every writer takes the project row's
    # lock, gets its own number, and proceeds. It orders writes; it never
    # refuses one. Clients use it as a resume cursor (`?since=N`).
    change_seq: Mapped[int] = mapped_column(
        BigInteger, default=0, server_default="0", nullable=False
    )
    updated_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        Index("ix_canvas_projects_owner_user_id", "owner_user_id"),
        # One canvas per series; free canvases are unlimited, so the
        # constraint has to be partial rather than a plain unique column.
        Index(
            "uq_canvas_projects_series",
            "series_id",
            unique=True,
            postgresql_where=text("series_id IS NOT NULL"),
        ),
    )


class CanvasNode(Base, TimestampMixin):
    """One card.

    Layout and identity are columns; what the card *shows* is opaque JSONB.
    The split is deliberate: pinning `data_json` into columns would turn every
    new card kind into an Alembic migration, while leaving `binding_asset_id`
    inside JSONB would keep asset hydration a Python scan of the whole canvas.
    """

    __tablename__ = "canvas_nodes"

    id: Mapped[str] = id_column("cnd")
    canvas_id: Mapped[str] = mapped_column(
        ForeignKey("canvas_projects.id", ondelete="CASCADE"), nullable=False
    )
    node_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    # Integers throughout, matching this schema's no-floats rule. Sub-pixel
    # drag precision is invisible on screen and rounding it away keeps the
    # equality comparisons on the compare-and-set path exact.
    position_x: Mapped[int] = mapped_column(Integer, nullable=False)
    position_y: Mapped[int] = mapped_column(Integer, nullable=False)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    z_index: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    # Denormalised out of `binding_json`: the one binding field read by a query
    # rather than by the renderer. Not an FK - `Asset` rows can be purged by
    # moderation and a card pointing at a gone asset must degrade to "stale",
    # not block the delete.
    binding_asset_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # Same shape and same reason as `binding_asset_id`: a skill card dropped
    # from the prompt library has to be hydrated on every canvas read, and
    # answering "which skills does this canvas bind?" out of JSONB would be a
    # scan. Also not an FK - a skill can be unpublished or deleted by its
    # owner and the card must degrade to "stale" rather than block that.
    binding_skill_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    binding_json: Mapped[dict[str, Any]] = mapped_column(default=dict, nullable=False)
    data_json: Mapped[dict[str, Any]] = mapped_column(default=dict, nullable=False)
    origin: Mapped[str] = mapped_column(
        String(16),
        default=CanvasNodeOrigin.USER,
        server_default=CanvasNodeOrigin.USER.value,
        nullable=False,
    )
    # Per-node compare-and-set. Replaces the old project-wide `revision`, so a
    # conflict is now scoped to the one card that actually moved under you.
    revision: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)
    seq: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        Index("ix_canvas_nodes_canvas_id_seq", "canvas_id", "seq"),
        Index(
            "ix_canvas_nodes_canvas_id_binding_asset_id",
            "canvas_id",
            "binding_asset_id",
            postgresql_where=text("binding_asset_id IS NOT NULL"),
        ),
        Index(
            "ix_canvas_nodes_canvas_id_binding_skill_id",
            "canvas_id",
            "binding_skill_id",
            postgresql_where=text("binding_skill_id IS NOT NULL"),
        ),
    )


class CanvasEdge(Base, TimestampMixin):
    """A connection between two cards.

    Edges carry no mutable payload, so they need no `revision`: creating one
    twice is caught by the endpoint uniqueness constraint and deleting a
    missing one is a no-op success. That is why only nodes are compare-and-set.
    """

    __tablename__ = "canvas_edges"

    id: Mapped[str] = id_column("cne")
    canvas_id: Mapped[str] = mapped_column(
        ForeignKey("canvas_projects.id", ondelete="CASCADE"), nullable=False
    )
    source_node_id: Mapped[str] = mapped_column(
        ForeignKey("canvas_nodes.id", ondelete="CASCADE"), nullable=False
    )
    target_node_id: Mapped[str] = mapped_column(
        ForeignKey("canvas_nodes.id", ondelete="CASCADE"), nullable=False
    )
    # Empty string, never NULL. Postgres treats NULLs as distinct inside a
    # unique constraint, so a nullable handle would let the very same edge
    # insert twice and silently defeat `uq_canvas_edges_endpoints`.
    source_handle: Mapped[str] = mapped_column(
        String(40), default="", server_default="", nullable=False
    )
    target_handle: Mapped[str] = mapped_column(
        String(40), default="", server_default="", nullable=False
    )
    edge_kind: Mapped[str] = mapped_column(
        String(32), default="link", server_default="link", nullable=False
    )
    seq: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        UniqueConstraint(
            "canvas_id",
            "source_node_id",
            "target_node_id",
            "source_handle",
            "target_handle",
            name="uq_canvas_edges_endpoints",
        ),
        # By target: the Agent's upstream-context walk. This is the concrete
        # reason edges are rows rather than entries in a blob - "what feeds
        # this card" is now an index seek instead of a scan of the whole graph.
        Index("ix_canvas_edges_canvas_id_target_node_id", "canvas_id", "target_node_id"),
        # By source: the renderer, and the bookkeeping in `delete_node`.
        Index("ix_canvas_edges_canvas_id_source_node_id", "canvas_id", "source_node_id"),
        Index("ix_canvas_edges_canvas_id_seq", "canvas_id", "seq"),
    )


class CanvasChange(Base):
    """Append-only change feed for one canvas.

    Plays the part `JobEvent` plays for the job stream: a gapless, durable log
    that backs `?since=N` catch-up and SSE resume by `Last-Event-ID`.

    It is not an optimisation. A deleted row cannot carry its own tombstone, so
    without this table a client that missed a delete would keep rendering a
    card the server no longer has, and no amount of polling would tell it
    otherwise.

    No `TimestampMixin`: rows are written once and never updated, so an
    `updated_at` that can only ever equal `created_at` is dead weight on the
    highest-volume table here.
    """

    __tablename__ = "canvas_changes"

    id: Mapped[str] = id_column("ccg")
    canvas_id: Mapped[str] = mapped_column(
        ForeignKey("canvas_projects.id", ondelete="CASCADE"), nullable=False
    )
    seq: Mapped[int] = mapped_column(BigInteger, nullable=False)
    entity_type: Mapped[str] = mapped_column(String(16), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(40), nullable=False)
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    actor: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_user_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # The row as it now stands, so a catching-up client can apply the change
    # without a second read. Empty for a delete - there is nothing to carry.
    payload_json: Mapped[dict[str, Any]] = mapped_column(default=dict, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (UniqueConstraint("canvas_id", "seq", name="uq_canvas_changes_canvas_seq"),)


class CanvasAgentRun(Base, TimestampMixin):
    """One Agent invocation on a canvas: read these cards, plan, generate.

    Sits *above* `GenerationJob` — each planned generation becomes one through
    `jobs_service.submit`, so credits, routing, moderation and skill context all
    still apply — and *beside* `AgentRun`, which is the raw bookkeeping for the
    planning LLM call.

    This is also where an Agent's live state lives, deliberately not in
    `CanvasNode.data_json`: putting it on the card would give the browser and
    the worker one cell to write again, which is the exact problem the row
    storage was introduced to remove.
    """

    __tablename__ = "canvas_agent_runs"

    id: Mapped[str] = id_column("car")
    canvas_id: Mapped[str] = mapped_column(
        ForeignKey("canvas_projects.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(24),
        default=CanvasAgentRunStatus.PLANNING,
        server_default=CanvasAgentRunStatus.PLANNING.value,
        nullable=False,
    )
    # `agent` for a planned run, `workflow` for one expanded from a skill
    # template. See `CanvasAgentRunOrigin`.
    origin: Mapped[str] = mapped_column(
        String(16),
        default=CanvasAgentRunOrigin.AGENT,
        server_default=CanvasAgentRunOrigin.AGENT.value,
        nullable=False,
    )
    goal: Mapped[str] = mapped_column(Text, nullable=False)
    # The `agent` card this run hangs off and anchors its output to. SET NULL
    # rather than CASCADE: deleting the card must not erase the record of what
    # the Agent did, or what it charged for.
    agent_node_id: Mapped[str | None] = mapped_column(
        ForeignKey("canvas_nodes.id", ondelete="SET NULL"), nullable=True
    )
    # Exactly which cards the planner was shown, after the upstream walk and
    # its caps. Recorded so a run is reproducible and auditable rather than a
    # black box that spent money.
    context_node_ids_json: Mapped[list[Any]] = mapped_column(default=list, nullable=False)
    context_digest_json: Mapped[dict[str, Any]] = mapped_column(default=dict, nullable=False)
    plan_json: Mapped[dict[str, Any]] = mapped_column(default=dict, nullable=False)
    # -> `AgentRun.id`. A plain column, not a foreign key, matching `EditPlan`:
    # deleting an agent must never erase the record of what it did.
    planner_agent_run_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    quoted_credits: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    max_credits: Mapped[int | None] = mapped_column(Integer, nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    failure_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_canvas_agent_runs_canvas_id_created_at", "canvas_id", "created_at"),
    )


class CanvasAgentTask(Base, TimestampMixin):
    """One planned generation, and the slot on the canvas its result lands in."""

    __tablename__ = "canvas_agent_tasks"

    id: Mapped[str] = id_column("cat")
    run_id: Mapped[str] = mapped_column(
        ForeignKey("canvas_agent_runs.id", ondelete="CASCADE"), nullable=False
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    operation: Mapped[str] = mapped_column(String(32), nullable=False)
    quality_tier: Mapped[str] = mapped_column(String(24), nullable=False)
    # The `GenerationParams` the planner emitted, after validation.
    request_json: Mapped[dict[str, Any]] = mapped_column(default=dict, nullable=False)
    # No matching column on `GenerationJob`. There is precedent for one
    # (`draft_id`, `linked_character_id`), but `generation_jobs` growing a
    # nullable pointer per consuming surface is a trend worth stopping, and the
    # reverse lookup below is a single index seek. Do not "helpfully" add it.
    generation_job_id: Mapped[str | None] = mapped_column(
        ForeignKey("generation_jobs.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(24),
        default=CanvasAgentTaskStatus.PLANNED,
        server_default=CanvasAgentTaskStatus.PLANNED.value,
        nullable=False,
    )
    # Reserved at plan time, so results land where the user was shown they
    # would even when tasks finish out of order.
    drop_x: Mapped[int] = mapped_column(Integer, nullable=False)
    drop_y: Mapped[int] = mapped_column(Integer, nullable=False)
    # NULL until the output actually became a card. Distinct from the job's own
    # `succeeded`, and it is what makes landing idempotent under a redelivered
    # terminal transition.
    result_node_id: Mapped[str | None] = mapped_column(
        ForeignKey("canvas_nodes.id", ondelete="SET NULL"), nullable=True
    )
    failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    failure_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("run_id", "ordinal", name="uq_canvas_agent_tasks_run_ordinal"),
        # The completion hook's only lookup, and it runs on every terminal
        # transition of every job in the system — so it must be an index seek.
        Index("ix_canvas_agent_tasks_generation_job_id", "generation_job_id"),
        Index("ix_canvas_agent_tasks_run_id_ordinal", "run_id", "ordinal"),
    )
