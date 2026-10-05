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
from app.models.enums import JobStatus, SystemLogLevel, SystemLogSource

logger = logging.getLogger(__name__)


def on_job_terminal(session: Session, job: GenerationJob) -> None:
    """Fan a finished job out to whatever was waiting on it.

    A no-op — one index seek returning nothing — for the great majority of
    jobs, which nothing outside the pipeline is waiting on.
    """
    _land_on_canvas(session, job)
    _land_voice_preview(session, job)


def _land_on_canvas(session: Session, job: GenerationJob) -> None:
    from app.domain.canvas import agent_service

    try:
        # A failed SELECT (missing table, constraint, …) aborts the whole
        # Postgres transaction. Without a savepoint the subsequent
        # `append_event` / credit writes in the same session raise
        # `InFailedSqlTransaction` and the job never reaches a terminal
        # status — exactly how a drifted canvas schema parked live jobs.
        with session.begin_nested():
            agent_service.land_job_result(session, job=job)
    except Exception:
        # Placing a card must never be able to fail a job whose credits were
        # just settled. The user's money is already spent and their output
        # already exists; losing the card is recoverable, losing the job is not.
        logger.exception("could not land job %s on its canvas", job.id)
        try:
            with session.begin_nested():
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


def _land_voice_preview(session: Session, job: GenerationJob) -> None:
    """A succeeded `target_voice_id` job (P7) becomes that voice's preview
    audio — if the voice still exists and still belongs to the job's owner.
    Isolated like the canvas landing: never fails a settled job."""
    voice_id = (job.request_json or {}).get("target_voice_id")
    if not voice_id or job.status != JobStatus.SUCCEEDED or not job.output_asset_id:
        return
    from app.models import CharacterVoice, CreationSkill

    try:
        with session.begin_nested():
            voice = session.get(CharacterVoice, str(voice_id))
            skill = session.get(CreationSkill, voice.skill_id) if voice is not None else None
            if voice is None or skill is None or skill.owner_user_id != job.user_id:
                return
            voice.preview_asset_id = job.output_asset_id
            voice.preview_job_id = job.id
            session.flush()
    except Exception:
        logger.exception("could not land job %s as a voice preview", job.id)
