/**
 * The "pipeline node → visible stage" mapping shared by every progress view —
 * the standalone `/jobs/[jobId]` page (`job-progress.tsx`) and the image
 * studio's inline result (`inline-image-result.tsx`). Kept in one place so
 * the two never drift apart (see `zaolang-generation-jobs` invariant #13:
 * `JobEvent.node_id`/`event_type` don't map 1:1, so this table is the only
 * source of truth for "which stage dot lit up").
 */

/**
 * Ordered stages aligned with the generation pipeline, mapped from event
 * types. No operation's graph ever has a distinct "sound" node — every graph
 * shape in `back/app/workflows/defaults.py` is this same 6-node shape (plus
 * the asset-planning detour for a character/scene/cover image job), and
 * `JobEventType.AUDIO` is never emitted anywhere — so there is exactly one
 * stage list for every operation, not a per-content-type set.
 */
export const STAGES = ['queued', 'safety', 'planning', 'generating', 'quality', 'done'] as const;
export type Stage = (typeof STAGES)[number];

export const STAGE_LABEL = {
  queued: 'stageQueued',
  safety: 'stageSafety',
  planning: 'stagePlanning',
  generating: 'stageGenerating',
  quality: 'stageQuality',
  done: 'stageDone',
} as const satisfies Record<Stage, string>;

export const STAGE_FOR_EVENT: Record<string, Stage> = {
  created: 'queued',
  queued: 'queued',
  safety: 'safety',
  safety_checked: 'safety',
  planning: 'planning',
  planned: 'planning',
  intent_routing: 'planning',
  routing: 'generating',
  routed: 'generating',
  generating: 'generating',
  provider_started: 'generating',
  progress: 'generating',
  awaiting_input: 'generating',
  // `JobEventType.AUDIO` is reserved but never emitted today — if it ever
  // fires, fold it into `generating` rather than a dedicated dot that would
  // never light up for image/video jobs.
  audio: 'generating',
  quality_check: 'quality',
  quality_checked: 'quality',
  settled: 'done',
  succeeded: 'done',
};

/** A generation-content-appropriate label for a stage — every stage but
 * `generating` uses the shared label, since only audio's own output
 * genuinely differs from the generic "generating" wording. */
export function stageLabelKey(stage: Stage, operation: string): string {
  if (stage === 'generating' && operation === 'audio_generation') return 'stageSound';
  return STAGE_LABEL[stage];
}

export const CHARACTER_VIEW_LABEL_KEY: Record<string, string> = {
  front: 'viewFront',
  side: 'viewSide',
  back: 'viewBack',
};
