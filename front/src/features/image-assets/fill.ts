import type { LookFillResponse, LookFillSlot } from '@/lib/api/types';

export const FILL_SLOTS: LookFillSlot[] = ['portrait', 'front', 'side', 'back', 'expressions'];
/** The backend's default expression set (`characters.fill.DEFAULT_FILL_EXPRESSIONS`). */
export const DEFAULT_FILL_EXPRESSIONS = [
  'neutral',
  'smile',
  'anger',
  'sad',
  'shock',
  'fear',
] as const;

export type FillStep =
  | { kind: 'running'; jobId: string; slots: LookFillSlot[] }
  | { kind: 'done' }
  | { kind: 'stuck'; slots: LookFillSlot[] };

/**
 * What a submit call of `…/looks/{id}:fill` means for the auto-continue
 * loop (补齐缺失, P2-4). The backend recomputes the plan from the card each
 * time, so after a wave succeeds the next call submits the next wave — or
 * nothing when the look is complete. Asking for exactly the same slots
 * again means the previous wave's images never landed on the card (a cap,
 * a lost write-back): stop instead of paying for the same wave forever.
 */
export function fillStep(
  response: Pick<LookFillResponse, 'submitted_job_id' | 'submitted_slots'>,
  previous: LookFillSlot[] | null,
): FillStep {
  if (!response.submitted_job_id) return { kind: 'done' };
  const slots = response.submitted_slots ?? [];
  if (previous && previous.length === slots.length && previous.every((s, i) => s === slots[i])) {
    return { kind: 'stuck', slots };
  }
  return { kind: 'running', jobId: response.submitted_job_id, slots };
}
