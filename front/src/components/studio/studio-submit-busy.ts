/**
 * When the video / clip studio must lock "生成我的版本" — HTTP submit in
 * flight, AI polish streaming, or any generation job that has not reached
 * a terminal status. Image / audio studios do not use this helper.
 *
 * Priority: submitting > polishPending > any in-flight job. The job check
 * walks every known job (not just the currently previewed one) so picking
 * an older succeeded version while another attempt is still running stays
 * locked.
 */

const TERMINAL_JOB_STATUSES = new Set(['succeeded', 'failed', 'cancelled', 'expired']);

export type StudioSubmitBusy = 'submitting' | 'polishing' | 'generating' | null;

export type StudioSubmitLabelKey = 'submit' | 'submitting' | 'submitGenerating' | 'submitPolishing';

export function studioSubmitLabelKey(busy: StudioSubmitBusy): StudioSubmitLabelKey {
  if (busy === 'submitting') return 'submitting';
  if (busy === 'polishing') return 'submitPolishing';
  if (busy === 'generating') return 'submitGenerating';
  return 'submit';
}

export function isJobInFlight(status: string | null | undefined): boolean {
  if (!status) return false;
  return !TERMINAL_JOB_STATUSES.has(status);
}

export function studioSubmitBusy({
  submitting,
  polishPending,
  jobs,
}: {
  submitting: boolean;
  polishPending: boolean;
  jobs: ReadonlyArray<{ status: string } | null | undefined>;
}): StudioSubmitBusy {
  if (submitting) return 'submitting';
  if (polishPending) return 'polishing';
  if (jobs.some((job) => job && isJobInFlight(job.status))) return 'generating';
  return null;
}
