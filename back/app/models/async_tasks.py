"""Work handed to an external provider that outlives the worker that started it.

A video render takes minutes. Blocking a Celery worker for that long wastes a
slot and, worse, leaves the job's event stream silent until the very end. So
`provider_generate` submits, writes one of these rows, and returns; the beat
task `poll_async_provider_tasks` checks it every few seconds, writes a
heartbeat event, and resumes the workflow where it left off once the upstream
finishes.

The job stays `RUNNING` the whole time. That is the one genuinely new fact
this table introduces: a `RUNNING` job may have no Celery task in flight at
all, and the row below is what proves the work was not lost.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, id_column


class AsyncProviderTask(Base, TimestampMixin):
    """One in-flight external task, plus everything needed to resume without it.

    `job_id` is unique: a job runs one provider attempt at a time, so a
    second row for the same job would mean two branches of one workflow are
    both waiting — which the runner cannot resume coherently.
    """

    __tablename__ = "provider_async_tasks"

    id: Mapped[str] = id_column("atask")
    job_id: Mapped[str] = mapped_column(
        ForeignKey("generation_jobs.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    # Where in the graph to resume from, and which port to take once the
    # outcome is known.
    node_id: Mapped[str] = mapped_column(String(64), nullable=False)
    # Router catalogue key (`"{endpoint_id}:{capability}"`), used to rebuild
    # the very same provider instance on the polling side.
    capability_name: Mapped[str] = mapped_column(String(120), nullable=False)
    external_task_id: Mapped[str] = mapped_column(String(200), nullable=False)
    # The `GenerationRequest` that produced this task and the slice of
    # workflow state the resumed run needs. JSON-safe by construction — see
    # `app.workflows.types.NodeResult.checkpoint`.
    request_json: Mapped[dict[str, Any]] = mapped_column(default=dict, nullable=False)
    state_checkpoint_json: Mapped[dict[str, Any]] = mapped_column(default=dict, nullable=False)
    # The `ProviderAttempt` opened at submit time, closed out when the task
    # settles, so a pending render is visible in the ops console immediately
    # rather than only after it finishes.
    provider_attempt_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    next_poll_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # When the render must be declared stuck rather than merely slow.
    deadline_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    poll_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Set while a scheduler tick is working on this row and cleared when it
    # is done. Two ticks overlapping would otherwise both resume the same
    # workflow — the same reason `state_machine.transition` claims a job
    # before acting on it.
    claimed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_provider_async_tasks_next_poll_at", "next_poll_at"),)
