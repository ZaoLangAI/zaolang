"""What happens elsewhere when a job reaches a terminal state.

One place, so a surface that wants to react to job completion does not have to
find and patch each of `state_machine.transition`'s call sites — the pipeline,
the async-polling worker, and `pipeline._fail`'s crash path all funnel through
there, and a hook wired into only some of them would work until it silently
did not.

Called from inside the caller's transaction, so a reaction either commits with
the terminal write or not at all. Every reaction is individually isolated: this
runs after credits have been captured or released, and no downstream bookkeeping
may turn a settled job back into a failure.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.domain.system_log import service as system_log
from app.models import GenerationJob
from app.models.enums import SystemLogLevel, SystemLogSource

logger = logging.getLogger(__name__)


def on_job_terminal(session: Session, job: GenerationJob) -> None:
    """Fan a finished job out to whatever was waiting on it.

    A no-op — one index seek returning nothing — for the great majority of
    jobs, which nothing outside the pipeline is waiting on.
    """
    _land_on_canvas(session, job)


def _land_on_canvas(session: Session, job: GenerationJob) -> None:
    from app.domain.canvas import agent_service

    try:
        agent_service.land_job_result(session, job=job)
    except Exception:
        # Placing a card must never be able to fail a job whose credits were
        # just settled. The user's money is already spent and their output
        # already exists; losing the card is recoverable, losing the job is not.
        logger.exception("could not land job %s on its canvas", job.id)
        try:
            system_log.emit(
                source=SystemLogSource.PIPELINE,
                event="canvas_land_failure",
                message=f"job={job.id}",
                dedup_key=f"canvas-land:{job.id}",
                level=SystemLogLevel.ERROR,
                job_id=job.id,
            )
        except Exception:  # pragma: no cover - logging must not raise either
            logger.exception("could not record the canvas landing failure")
