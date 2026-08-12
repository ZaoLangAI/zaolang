"""A generation job parked on a question only its author can answer.

Mirrors `app.models.async_tasks.AsyncProviderTask` in shape and intent — both
are "someone still has to come back for this job" rows a suspended
`WorkflowRunner` walk leaves behind — but the two are never merged into one
table: an external render is claimed and polled by a scheduler on a fixed
cadence, while this one is answered once, by one specific user, whenever they
get to it. Overloading a single table with both lifecycles would mean every
query has to branch on which kind of row it is looking at.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, id_column


class WorkflowInputRequest(Base, TimestampMixin):
    """One `copy_generate` node's follow-up questions, awaiting the author.

    `job_id` is unique for the same reason `AsyncProviderTask.job_id` is: a
    job walks one graph at a time, so a second row for the same job would
    mean two suspensions are both waiting, which the runner cannot resume
    coherently.
    """

    __tablename__ = "workflow_input_requests"

    id: Mapped[str] = id_column("wir")
    job_id: Mapped[str] = mapped_column(
        ForeignKey("generation_jobs.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    # Where in the graph to resume from once the answers are in.
    node_id: Mapped[str] = mapped_column(String(64), nullable=False)
    # Which `ctx.state` key the node's first-pass output (and, once answered,
    # the merged answers) live under — the same key a downstream node reads.
    output_key: Mapped[str] = mapped_column(String(40), nullable=False)
    # `[{"id","kind","prompt","options":[{"value","label"}],"required"}]` —
    # the same shape `app.agents.copywriter.clarify` already produces, so the
    # C-end renderer that already exists for the pre-submission clarify flow
    # can be reused verbatim.
    questions_json: Mapped[list[Any]] = mapped_column(default=list, nullable=False)
    # The slice of `ctx.state` the resumed run cannot rebuild for itself.
    # JSON-safe by construction — see `app.workflows.types.NodeResult.checkpoint`.
    state_checkpoint_json: Mapped[dict[str, Any]] = mapped_column(default=dict, nullable=False)
    # When an unanswered request is abandoned rather than merely slow — an
    # author is not a provider SLA, so this is intentionally generous compared
    # to `AsyncProviderTask.deadline_at`.
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("ix_workflow_input_requests_expires_at", "expires_at"),)
