import { STAGES, STAGE_FOR_EVENT, type Stage } from './job-stages';

/**
 * Which stage a job is showing, and which ones it has been through.
 *
 * Derived rather than stored: `JobEvent`s arrive out of a pipeline that can
 * loop (a multi-view character job re-enters `asset_planning` once per view),
 * so "furthest reached" and "currently displayed" are different questions and
 * neither is a field on the job.
 *
 * This was copied verbatim in three places — `job-progress.tsx`,
 * `inline-image-result.tsx` and `inline-video-result.tsx` — before the canvas
 * workbench needed a fourth. The subtleties below are exactly the kind that
 * drift apart across copies.
 */

const FINISHED_STATUSES = new Set(['succeeded', 'failed', 'cancelled', 'expired']);

export interface JobStageState {
  /** Every stage the events say the job has been through. */
  reached: Set<Stage>;
  /** The one to highlight. */
  displayStage: Stage;
  /** In a terminal status — used to stop pulsing the active dot. */
  finished: boolean;
  awaitingInput: boolean;
  /** Stable string of `reached`, for animation effect dependencies: a `Set`
   * identity changes on every render and would re-fire them forever. */
  reachedKey: string;
}

/**
 * `status` and `events` are separate arguments rather than a job object: the
 * events a caller wants are the *streamed* ones (`useJobStream`), not the
 * snapshot embedded on `GenerationJob`, and taking the job would quietly read
 * the wrong list.
 */
export function jobStageState(
  status: string,
  events: readonly { event_type: string }[],
): JobStageState {
  const reached = new Set<Stage>();
  for (const event of events) {
    const stage = STAGE_FOR_EVENT[event.event_type];
    if (stage) reached.add(stage);
  }
  // A succeeded job lights every dot even if its events were sparse — a
  // provider that never emitted a `quality` event still passed through it.
  if (status === 'succeeded') for (const stage of STAGES) reached.add(stage);

  const activeIndex = STAGES.findIndex((stage) => !reached.has(stage));
  const finished = FINISHED_STATUSES.has(status);
  const awaitingInput = status === 'awaiting_input';

  const displayStage: Stage = awaitingInput
    ? // The job is parked on a follow-up question, which is raised from the
      // planning node — showing the next unreached stage would claim progress
      // that is waiting on the user.
      'planning'
    : finished && status !== 'succeeded'
      ? // Failed or cancelled: show where it got to, not where it was going.
        ([...STAGES].reverse().find((stage) => reached.has(stage)) ?? 'queued')
      : (STAGES[activeIndex] ?? 'done');

  return {
    reached,
    displayStage,
    finished,
    awaitingInput,
    reachedKey: STAGES.filter((stage) => reached.has(stage)).join(','),
  };
}

/**
 * The `jobPage` title for a job that stopped without a result — what the
 * stage area says instead of an in-flight caption and a 100% that a failed
 * event leaves behind. Null while running or after success.
 */
export function stoppedTitleKey(status: string): 'failedTitle' | 'cancelledTitle' | null {
  if (status === 'cancelled') return 'cancelledTitle';
  if (status === 'failed' || status === 'expired') return 'failedTitle';
  return null;
}
