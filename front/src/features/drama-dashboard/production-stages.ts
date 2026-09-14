/**
 * The episode production board's model — pure, so every stage and film-strip
 * rule is testable without the panel. Everything here is derived from data
 * the episode workspace already loads (script, linked drafts, cuts, exports,
 * `canonical_work_id`); nothing is estimated or invented: a segment with no
 * generated video has no duration and says so.
 */

import type { ScriptDocument } from '@/features/script/api';
import {
  dialogueLineKey,
  linkedCharacterCount,
  linkedSceneCount,
} from '@/features/script/batch-plan';
import {
  orderedBreakpointKeys,
  type BreakpointVideoBinding,
} from '@/features/script/script-breakpoint';
import type { Draft, GenerationJob } from '@/lib/api/types';

export const PRODUCTION_STAGES = [
  'script',
  'characters',
  'scenes',
  'shots',
  'voice',
  'edit',
  'export',
  'publish',
] as const;

export type ProductionStageKey = (typeof PRODUCTION_STAGES)[number];
export type ProductionStageState = 'done' | 'active' | 'todo';

export interface ProductionStage {
  key: ProductionStageKey;
  state: ProductionStageState;
  /** Counted stages only (characters, scenes, shots, voice). */
  done: number | null;
  total: number | null;
}

export interface ProductionInput {
  hasScript: boolean;
  script: ScriptDocument | null;
  /** `indexBreakpointVideos(drafts, script.scenes)`. */
  bindings: Record<string, BreakpointVideoBinding>;
  /** `dubbedDialogueKeys(drafts)`. */
  dubbedKeys: ReadonlySet<string>;
  cutCount: number;
  exportStatuses: readonly string[];
  published: boolean;
}

function flagStage(key: ProductionStageKey, done: boolean, started = false): ProductionStage {
  return { key, state: done ? 'done' : started ? 'active' : 'todo', done: null, total: null };
}

function countStage(
  key: ProductionStageKey,
  done: number,
  total: number,
  { started = done > 0, emptyIsDone }: { started?: boolean; emptyIsDone: boolean },
): ProductionStage {
  const complete = total === 0 ? emptyIsDone : done >= total;
  return { key, state: complete ? 'done' : started ? 'active' : 'todo', done, total };
}

function dialogueKeys(script: ScriptDocument): string[] {
  const keys: string[] = [];
  for (const scene of script.scenes) {
    scene.blocks.forEach((block, blockIndex) => {
      if (block.type === 'dialogue' && block.text.trim()) {
        keys.push(dialogueLineKey(scene.heading, blockIndex));
      }
    });
  }
  return keys;
}

/** 剧本 → 角色 → 场景 → 分镜 → 配音 → 剪辑 → 成片 → 发布. A script with no
 * characters, scenes or dialogue has nothing to do at that stage (done);
 * one with no breakpoints has not been broken into shots yet (todo). */
export function episodeProductionStages(input: ProductionInput): ProductionStage[] {
  const script = input.hasScript ? input.script : null;
  const keys = script ? orderedBreakpointKeys(script) : [];
  const lines = script ? dialogueKeys(script) : [];
  const nothingLeft = { emptyIsDone: Boolean(script) };
  return [
    flagStage('script', Boolean(script)),
    countStage(
      'characters',
      script ? linkedCharacterCount(script) : 0,
      script?.characters.length ?? 0,
      nothingLeft,
    ),
    countStage('scenes', script ? linkedSceneCount(script) : 0, script?.scenes.length ?? 0, nothingLeft),
    countStage(
      'shots',
      keys.filter((key) => input.bindings[key]?.outputAssetId).length,
      keys.length,
      { started: keys.some((key) => key in input.bindings), emptyIsDone: false },
    ),
    countStage('voice', lines.filter((key) => input.dubbedKeys.has(key)).length, lines.length, nothingLeft),
    flagStage('edit', input.cutCount > 0),
    flagStage('export', input.exportStatuses.includes('succeeded'), input.exportStatuses.length > 0),
    flagStage('publish', input.published),
  ];
}

/** The first stage that still needs work — where the author is "at". */
export function currentProductionStage(stages: ProductionStage[]): ProductionStageKey | null {
  return stages.find((stage) => stage.state !== 'done')?.key ?? null;
}

export type ShotStatus = 'ready' | 'generating' | 'failed' | 'missing';

const UNFINISHED_JOB_STATUSES = new Set(['created', 'queued', 'submitted', 'running', 'awaiting_input']);

export interface ProductionShot {
  key: string;
  heading: string;
  /** `S01·2`: scene number, then the segment's 1-based ordinal in it. */
  label: string;
  status: ShotStatus;
  /** From the draft's output asset; `null` until a video exists. */
  durationSeconds: number | null;
  draftId: string | null;
}

/** One film-strip card per breakpoint segment, in shoot order. A bound
 * draft with no output is `generating` until its jobs are known to have all
 * ended without a success — then `failed`. */
export function productionShots(
  script: ScriptDocument,
  bindings: Record<string, BreakpointVideoBinding>,
  draftsById: Readonly<Record<string, Draft>>,
  jobsByDraft: Readonly<Record<string, readonly GenerationJob[]>> = {},
): ProductionShot[] {
  const sceneNumber = new Map<string, number>();
  script.scenes.forEach((scene, index) => {
    if (!sceneNumber.has(scene.heading)) sceneNumber.set(scene.heading, index + 1);
  });
  return orderedBreakpointKeys(script).map((key) => {
    const hash = key.lastIndexOf('#');
    const heading = key.slice(0, hash);
    const ordinal = Number(key.slice(hash + 1));
    const binding = bindings[key];
    const draft = binding ? draftsById[binding.draftId] : undefined;
    const durationMs = binding?.outputAssetId ? draft?.duration_ms : null;
    let status: ShotStatus = binding?.outputAssetId ? 'ready' : binding ? 'generating' : 'missing';
    const jobs = binding ? jobsByDraft[binding.draftId] : undefined;
    if (
      status === 'generating' &&
      jobs &&
      jobs.length > 0 &&
      !jobs.some((job) => job.status === 'succeeded' || UNFINISHED_JOB_STATUSES.has(job.status))
    ) {
      status = 'failed';
    }
    return {
      key,
      heading,
      label: `S${String(sceneNumber.get(heading) ?? 0).padStart(2, '0')}·${ordinal + 1}`,
      status,
      durationSeconds: durationMs ? durationMs / 1000 : null,
      draftId: binding?.draftId ?? null,
    };
  });
}

/** Episode-linked video drafts whose `link_breakpoint_key` no longer names a
 * segment of the current script (the scene was renamed or the breakpoint
 * removed) — shown as 未匹配 rather than silently dropped. */
export function unmatchedVideoDraftCount(
  script: ScriptDocument,
  drafts: readonly Draft[],
): number {
  const keys = new Set(orderedBreakpointKeys(script));
  return drafts.filter((draft) => {
    const operation = draft.params?.operation;
    const key = draft.params?.link_breakpoint_key;
    const isVideo =
      !operation || operation === 'text_to_video' || operation === 'image_to_video';
    return isVideo && typeof key === 'string' && key !== '' && !keys.has(key);
  }).length;
}

/** Credits actually charged across the viewer's own jobs on these drafts.
 * In-flight jobs only hold a reservation, so they don't count yet. */
export function creditsSpent(jobs: readonly GenerationJob[]): number {
  return jobs.reduce((sum, job) => sum + (job.actual_credits ?? 0), 0);
}

/** Succeeded generations per draft — the take number on a film-strip card. */
export function takeCount(jobs: readonly GenerationJob[]): number {
  return jobs.filter((job) => job.status === 'succeeded').length;
}
