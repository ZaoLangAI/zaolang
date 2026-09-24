'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

import { api, newIdempotencyKey } from '@/lib/api/client';
import { ApiError, isApiError } from '@/lib/api/errors';
import type {
  Draft,
  GenerationJob,
  JobStatus,
  Operation,
  QualityTier,
} from '@/lib/api/types';
import { STUDIO_PROMPT_MAX_LENGTH } from '@/lib/prompt-limits';
import { FALLBACK_VOICES } from '@/lib/use-generation-models';

import type { ScriptCharacter, ScriptDocument, ScriptScene } from './api';
import type { PendingAudio, PendingVideo } from './batch-plan';
import { characterImagePrompt, sceneImagePrompt } from './script-prompts';
import { type BreakpointVideoBinding } from './script-breakpoint';

export type BatchKind = 'characters' | 'scenes' | 'videos' | 'audio';
export type BatchItemKind = 'character' | 'scene' | 'video' | 'audio';
export type BatchItemStatus =
  | 'queued'
  | 'submitting'
  | 'running'
  | 'succeeded'
  | 'failed'
  | 'paused';

export interface BatchItemState {
  kind: BatchItemKind;
  id: string;
  label: string;
  status: BatchItemStatus;
  jobId?: string;
  draftId?: string;
  error?: string;
}

export interface BatchParams {
  qualityTier: QualityTier;
  durationSeconds: number;
  aspectRatio: string;
  resolution: '480p' | '720p' | '1080p' | '2K';
  /** Only meaningful for `kind: 'audio'` — the voice every dubbed line in
   * this batch is submitted with (see `PendingAudio`/`runAudio`). */
  voice?: string;
}

export const DEFAULT_CHARACTER_PARAMS: BatchParams = {
  qualityTier: 'standard',
  durationSeconds: 0,
  aspectRatio: '3:4',
  resolution: '1080p',
};

export const DEFAULT_SCENE_PARAMS: BatchParams = {
  qualityTier: 'standard',
  durationSeconds: 0,
  aspectRatio: '16:9',
  resolution: '1080p',
};

export const DEFAULT_VIDEO_PARAMS: BatchParams = {
  qualityTier: 'standard',
  durationSeconds: 8,
  aspectRatio: '9:16',
  resolution: '1080p',
};

// Audio has no aspect/resolution control of its own — `aspectRatio` rides
// along as the same placeholder `AudioGenerationStudio` uses, purely
// because the shared submit schema always wants a valid one.
export const DEFAULT_AUDIO_PARAMS: BatchParams = {
  qualityTier: 'standard',
  durationSeconds: 0,
  aspectRatio: '16:9',
  resolution: '1080p',
  voice: FALLBACK_VOICES[0],
};

export interface BatchQuote {
  unitCredits: number;
  totalCredits: number;
  count: number;
  availableCredits: number;
  /** What the user's own monthly spend cap still allows; null = no cap. */
  periodRemaining: number | null;
  withinSpendLimit: boolean;
  /** Enough balance *and* within the monthly cap. */
  sufficient: boolean;
}

/** `POST /v1/generation-jobs/quote:batch` — an exact sum of per-line quotes. */
interface BatchQuoteResult {
  items: Array<{ unit_credits: number; count: number; credits: number }>;
  total_credits: number;
  available_credits: number;
  period_remaining: number | null;
  within_spend_limit: boolean;
  sufficient: boolean;
}

const SUBMIT_GAP_MS = 5500;
const POLL_MS = 2500;
const IMAGE_CONCURRENCY = 3;
const STORAGE_VERSION = 1;
const TERMINAL: ReadonlySet<JobStatus> = new Set([
  'succeeded',
  'failed',
  'cancelled',
  'expired',
]);

type StoredBatch = {
  v: typeof STORAGE_VERSION;
  kind: BatchKind;
  params: BatchParams;
  items: BatchItemState[];
  document: ScriptDocument | null;
  videos: PendingVideo[];
  audios?: PendingAudio[];
  unitCredits: number;
};

function storageKey(episodeId: string): string {
  return `zl.scriptBatch.${episodeId}`;
}

function readStore(episodeId: string): StoredBatch | null {
  if (typeof sessionStorage === 'undefined') return null;
  try {
    const raw = sessionStorage.getItem(storageKey(episodeId));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as StoredBatch;
    if (parsed.v !== STORAGE_VERSION || !Array.isArray(parsed.items)) return null;
    return parsed;
  } catch {
    return null;
  }
}

function writeStore(episodeId: string, value: StoredBatch | null): void {
  if (typeof sessionStorage === 'undefined') return;
  try {
    if (!value) sessionStorage.removeItem(storageKey(episodeId));
    else sessionStorage.setItem(storageKey(episodeId), JSON.stringify(value));
  } catch {
    // Quota or private mode — progress just will not survive a refresh.
  }
}

function sleep(ms: number, signal: AbortSignal): Promise<void> {
  if (signal.aborted || ms <= 0) return Promise.resolve();
  return new Promise((resolve) => {
    const timer = setTimeout(resolve, ms);
    const onAbort = () => {
      clearTimeout(timer);
      resolve();
    };
    signal.addEventListener('abort', onAbort, { once: true });
  });
}

function clipPrompt(value: string): string {
  return value.slice(0, STUDIO_PROMPT_MAX_LENGTH);
}

export function quoteForBatch(
  kind: BatchKind,
  params: BatchParams,
  count: number,
): Promise<BatchQuote> {
  const operation: Operation =
    kind === 'videos' ? 'text_to_video' : kind === 'audio' ? 'audio_generation' : 'text_to_image';
  return api
    .post<BatchQuoteResult>('/v1/generation-jobs/quote:batch', {
      items: [
        {
          operation,
          quality_tier: params.qualityTier,
          duration_seconds: kind === 'videos' ? params.durationSeconds : 0,
          asset_kind: kind === 'characters' ? 'character' : kind === 'scenes' ? 'scene' : 'general',
          character_views: kind === 'characters' ? ['front'] : null,
          count: Math.max(1, count),
        },
      ],
    })
    .then((quote) => ({
      unitCredits: quote.items[0]?.unit_credits ?? 0,
      totalCredits: quote.total_credits,
      count,
      availableCredits: quote.available_credits,
      periodRemaining: quote.period_remaining,
      withinSpendLimit: quote.within_spend_limit,
      sufficient: quote.sufficient,
    }));
}

export function inFlightIds(
  items: Iterable<BatchItemState>,
  kind: BatchItemKind,
): Set<string> {
  const ids = new Set<string>();
  for (const item of items) {
    if (item.kind !== kind) continue;
    if (item.status === 'queued' || item.status === 'submitting' || item.status === 'running') {
      ids.add(item.id);
    }
  }
  return ids;
}

function isActiveStatus(status: BatchItemStatus): boolean {
  return status === 'queued' || status === 'submitting' || status === 'running';
}

export async function submitJob(input: {
  operation: Operation;
  qualityTier: QualityTier;
  prompt: string;
  aspectRatio: string;
  durationSeconds: number;
  draftTitle: string;
  draftId?: string;
  assetKind?: 'character' | 'scene';
  subjectNameHint?: string;
  targetCharacterId?: string | null;
  targetSceneId?: string | null;
  characterIds?: string[];
  sceneIds?: string[];
  videoOptions?: {
    resolution?: '480p' | '720p' | '1080p' | '2K';
    reference_mode: 'input_references' | 'frame_images';
    first_frame_asset_id?: string | null;
    /** A 白膜 render among `referenceAssetIds` — see
     * `VideoGenerationOptions.reference_video_role`. */
    reference_video_role?: 'motion_guide' | null;
  };
  referenceAssetIds?: string[];
  linkEpisodeId?: string;
  linkBreakpointKey?: string;
  extra?: Record<string, unknown>;
  maxCredits: number;
}): Promise<GenerationJob> {
  let draftId = input.draftId;
  if (!draftId) {
    const draft = await api.post<Draft>('/v1/drafts', {
      source_work_id: null,
      title: input.draftTitle,
      params: {
        prompt: input.prompt,
        aspect_ratio: input.aspectRatio,
        duration_seconds: input.durationSeconds,
        operation: input.operation,
        quality_tier: input.qualityTier,
        video_options: input.videoOptions,
        asset_kind: input.assetKind ?? 'general',
        ...(input.linkEpisodeId ? { link_episode_id: input.linkEpisodeId } : undefined),
        ...(input.linkBreakpointKey ? { link_breakpoint_key: input.linkBreakpointKey } : undefined),
      },
    });
    draftId = draft.id;
  }
  return api.post<GenerationJob>(
    '/v1/generation-jobs',
    {
      operation: input.operation,
      quality_tier: input.qualityTier,
      draft_id: draftId,
      params: {
        prompt: input.prompt,
        aspect_ratio: input.aspectRatio,
        duration_seconds: input.durationSeconds,
        reference_asset_ids: input.referenceAssetIds ?? [],
        video_options: input.videoOptions,
        character_ids: input.characterIds ?? [],
        scene_ids: input.sceneIds ?? [],
        skill_ids: [],
        style_gallery_id: null,
        asset_kind: input.assetKind ?? 'general',
        video_asset_kind: 'general',
        character_views: input.assetKind === 'character' ? ['front'] : null,
        target_character_id: input.targetCharacterId ?? null,
        target_scene_id: input.targetSceneId ?? null,
        subject_name_hint: input.subjectNameHint,
        auto_attach_asset: true,
        forced_model: null,
        extra: input.extra ?? {},
      },
      max_credits: input.maxCredits,
    },
    { idempotencyKey: newIdempotencyKey() },
  );
}

export async function pollJob(jobId: string, signal: AbortSignal): Promise<GenerationJob> {
  while (!signal.aborted) {
    const job = await api.get<GenerationJob>(`/v1/generation-jobs/${jobId}`);
    if (TERMINAL.has(job.status)) return job;
    await sleep(POLL_MS, signal);
  }
  throw new DOMException('Aborted', 'AbortError');
}

export function useScriptBatch({
  episodeId,
  videoBindings,
  onLink,
  onVideoDraftCreated,
  onLibraryChanged,
}: {
  episodeId: string;
  videoBindings: Record<string, BreakpointVideoBinding>;
  onLink: (
    update:
      | { kind: 'character'; name: string; refId: string }
      | { kind: 'scene'; heading: string; refId: string },
  ) => Promise<void>;
  onVideoDraftCreated: () => void;
  onLibraryChanged: () => void;
}) {
  const [items, setItems] = useState<BatchItemState[]>([]);
  const [running, setRunning] = useState(false);
  const [paused, setPaused] = useState(false);

  // Every one of these is a "latest value" ref, only ever read from inside
  // a callback that fires later (a poll, a submit, a click) — never read or
  // written synchronously during render itself — so the sync happens in an
  // effect (post-commit) rather than inline in the render body.
  const itemsRef = useRef(items);
  const onLinkRef = useRef(onLink);
  const onVideoDraftCreatedRef = useRef(onVideoDraftCreated);
  const onLibraryChangedRef = useRef(onLibraryChanged);
  const bindingsRef = useRef(videoBindings);
  useEffect(() => {
    itemsRef.current = items;
  }, [items]);
  useEffect(() => {
    onLinkRef.current = onLink;
  }, [onLink]);
  useEffect(() => {
    onVideoDraftCreatedRef.current = onVideoDraftCreated;
  }, [onVideoDraftCreated]);
  useEffect(() => {
    onLibraryChangedRef.current = onLibraryChanged;
  }, [onLibraryChanged]);
  useEffect(() => {
    bindingsRef.current = { ...bindingsRef.current, ...videoBindings };
  }, [videoBindings]);
  const abortRef = useRef<AbortController | null>(null);
  const lastSubmitAt = useRef(0);
  const persistKind = useRef<BatchKind | null>(null);
  const persistParams = useRef<BatchParams>(DEFAULT_CHARACTER_PARAMS);
  const persistDocument = useRef<ScriptDocument | null>(null);
  const pendingVideosRef = useRef<PendingVideo[]>([]);
  const pendingAudiosRef = useRef<PendingAudio[]>([]);
  const unitCreditsRef = useRef(0);
  const restored = useRef(false);

  const persist = useCallback(
    (nextItems: BatchItemState[]) => {
      const kind = persistKind.current;
      if (!kind) return;
      const active = nextItems.some(
        (item) => isActiveStatus(item.status) || item.status === 'paused' || item.status === 'failed',
      );
      writeStore(
        episodeId,
        active
          ? {
              v: STORAGE_VERSION,
              kind,
              params: persistParams.current,
              items: nextItems,
              document: persistDocument.current,
              videos: pendingVideosRef.current,
              audios: pendingAudiosRef.current,
              unitCredits: unitCreditsRef.current,
            }
          : null,
      );
    },
    [episodeId],
  );

  const patchItem = useCallback(
    (kind: BatchItemKind, id: string, patch: Partial<BatchItemState>) => {
      setItems((current) => {
        const next = current.map((item) =>
          item.kind === kind && item.id === id ? { ...item, ...patch } : item,
        );
        persist(next);
        return next;
      });
    },
    [persist],
  );

  const paceSubmit = useCallback(async (signal: AbortSignal) => {
    const wait = Math.max(0, SUBMIT_GAP_MS - (Date.now() - lastSubmitAt.current));
    await sleep(wait, signal);
    lastSubmitAt.current = Date.now();
  }, []);

  const finishImage = useCallback(
    async (item: BatchItemState, job: GenerationJob) => {
      if (job.status !== 'succeeded') {
        patchItem(item.kind, item.id, {
          status: 'failed',
          error: job.failure_message || job.status,
        });
        return;
      }
      const refId =
        item.kind === 'character' ? job.linked_character_id : job.linked_scene_id;
      if (!refId) {
        patchItem(item.kind, item.id, {
          status: 'failed',
          error: 'missing_link',
        });
        return;
      }
      await onLinkRef.current(
        item.kind === 'character'
          ? { kind: 'character', name: item.id, refId }
          : { kind: 'scene', heading: item.id, refId },
      );
      onLibraryChangedRef.current();
      patchItem(item.kind, item.id, { status: 'succeeded', error: undefined });
    },
    [patchItem],
  );

  const runImage = useCallback(
    async (
      item: BatchItemState,
      source: ScriptCharacter | ScriptScene,
      params: BatchParams,
      unitCredits: number,
      signal: AbortSignal,
    ) => {
      patchItem(item.kind, item.id, { status: 'submitting', error: undefined });
      await paceSubmit(signal);
      if (signal.aborted) return;
      const isCharacter = item.kind === 'character';
      const prompt = clipPrompt(
        isCharacter
          ? characterImagePrompt(source as ScriptCharacter)
          : sceneImagePrompt(source as ScriptScene),
      );
      try {
        const job = await submitJob({
          operation: 'text_to_image',
          qualityTier: params.qualityTier,
          prompt,
          aspectRatio: params.aspectRatio,
          durationSeconds: 0,
          draftTitle: item.label,
          assetKind: isCharacter ? 'character' : 'scene',
          subjectNameHint: item.id.slice(0, 60),
          maxCredits: unitCredits,
        });
        patchItem(item.kind, item.id, {
          status: 'running',
          jobId: job.id,
          draftId: job.draft_id ?? undefined,
        });
        const finished = TERMINAL.has(job.status) ? job : await pollJob(job.id, signal);
        await finishImage(item, finished);
      } catch (error) {
        if (signal.aborted) return;
        patchItem(item.kind, item.id, {
          status: 'failed',
          error: isApiError(error) ? error.message : 'failed',
        });
      }
    },
    [finishImage, paceSubmit, patchItem],
  );

  const runVideo = useCallback(
    async (
      item: BatchItemState,
      video: PendingVideo,
      params: BatchParams,
      unitCredits: number,
      signal: AbortSignal,
    ) => {
      patchItem('video', item.id, { status: 'submitting', error: undefined });
      await paceSubmit(signal);
      if (signal.aborted) return 'aborted' as const;
      try {
        const existing = itemsRef.current.find((row) => row.kind === 'video' && row.id === item.id);
        const job = await submitJob({
          operation: 'text_to_video',
          qualityTier: params.qualityTier,
          prompt: clipPrompt(video.prompt),
          aspectRatio: params.aspectRatio,
          durationSeconds: params.durationSeconds,
          draftTitle: video.heading,
          draftId: existing?.draftId,
          characterIds: video.characterIds,
          sceneIds: video.sceneId ? [video.sceneId] : [],
          videoOptions: {
            resolution: params.resolution,
            reference_mode: 'input_references',
          },
          linkEpisodeId: episodeId,
          linkBreakpointKey: video.key,
          maxCredits: unitCredits,
        });
        patchItem('video', item.id, {
          status: 'running',
          jobId: job.id,
          draftId: job.draft_id ?? undefined,
        });
        onVideoDraftCreatedRef.current();
        const finished = TERMINAL.has(job.status) ? job : await pollJob(job.id, signal);
        if (finished.status !== 'succeeded' || !finished.output_asset_id) {
          patchItem('video', item.id, {
            status: 'failed',
            error: finished.failure_message || finished.status,
          });
          return 'failed' as const;
        }
        bindingsRef.current = {
          ...bindingsRef.current,
          [video.key]: {
            draftId: finished.draft_id ?? job.draft_id ?? '',
            latestJobId: finished.id,
            outputAssetId: finished.output_asset_id,
          },
        };
        patchItem('video', item.id, { status: 'succeeded', error: undefined });
        return 'succeeded' as const;
      } catch (error) {
        if (signal.aborted) return 'aborted' as const;
        patchItem('video', item.id, {
          status: 'failed',
          error: isApiError(error) ? error.message : 'failed',
        });
        return 'failed' as const;
      }
    },
    [episodeId, paceSubmit, patchItem],
  );

  const runImagePool = useCallback(
    async (
      work: Array<{ item: BatchItemState; source: ScriptCharacter | ScriptScene }>,
      params: BatchParams,
      unitCredits: number,
      signal: AbortSignal,
    ) => {
      let cursor = 0;
      const workers = Array.from({ length: Math.min(IMAGE_CONCURRENCY, work.length) }, async () => {
        while (!signal.aborted) {
          const index = cursor;
          cursor += 1;
          const next = work[index];
          if (!next) return;
          await runImage(next.item, next.source, params, unitCredits, signal);
        }
      });
      await Promise.all(workers);
    },
    [runImage],
  );

  const pauseRemainingQueued = useCallback(
    (kind: 'video' | 'audio') => {
      setItems((current) => {
        const next = current.map((row) =>
          row.kind === kind && row.status === 'queued' ? { ...row, status: 'paused' as const } : row,
        );
        persist(next);
        return next;
      });
      setPaused(true);
    },
    [persist],
  );

  const runVideoQueue = useCallback(
    async (videos: PendingVideo[], signal: AbortSignal) => {
      for (const video of videos) {
        if (signal.aborted) break;
        const item: BatchItemState = {
          kind: 'video',
          id: video.key,
          label: video.heading,
          status: 'queued',
        };
        const result = await runVideo(
          item,
          video,
          persistParams.current,
          unitCreditsRef.current,
          signal,
        );
        if (result === 'failed') {
          pauseRemainingQueued('video');
          break;
        }
      }
    },
    [pauseRemainingQueued, runVideo],
  );

  const runAudio = useCallback(
    async (
      item: BatchItemState,
      audio: PendingAudio,
      params: BatchParams,
      unitCredits: number,
      signal: AbortSignal,
    ) => {
      patchItem('audio', item.id, { status: 'submitting', error: undefined });
      await paceSubmit(signal);
      if (signal.aborted) return 'aborted' as const;
      try {
        const existing = itemsRef.current.find((row) => row.kind === 'audio' && row.id === item.id);
        const job = await submitJob({
          operation: 'audio_generation',
          qualityTier: params.qualityTier,
          prompt: clipPrompt(audio.text),
          aspectRatio: params.aspectRatio,
          durationSeconds: 0,
          draftTitle: audio.heading,
          draftId: existing?.draftId,
          linkEpisodeId: episodeId,
          linkBreakpointKey: audio.key,
          extra: { voice: params.voice || FALLBACK_VOICES[0] },
          maxCredits: unitCredits,
        });
        patchItem('audio', item.id, {
          status: 'running',
          jobId: job.id,
          draftId: job.draft_id ?? undefined,
        });
        const finished = TERMINAL.has(job.status) ? job : await pollJob(job.id, signal);
        if (finished.status !== 'succeeded') {
          patchItem('audio', item.id, {
            status: 'failed',
            error: finished.failure_message || finished.status,
          });
          return 'failed' as const;
        }
        onLibraryChangedRef.current();
        patchItem('audio', item.id, { status: 'succeeded', error: undefined });
        return 'succeeded' as const;
      } catch (error) {
        if (signal.aborted) return 'aborted' as const;
        patchItem('audio', item.id, {
          status: 'failed',
          error: isApiError(error) ? error.message : 'failed',
        });
        return 'failed' as const;
      }
    },
    [episodeId, paceSubmit, patchItem],
  );

  const runAudioQueue = useCallback(
    async (audios: PendingAudio[], signal: AbortSignal) => {
      for (const audio of audios) {
        if (signal.aborted) break;
        const item: BatchItemState = {
          kind: 'audio',
          id: audio.key,
          label: audio.heading,
          status: 'queued',
        };
        const result = await runAudio(
          item,
          audio,
          persistParams.current,
          unitCreditsRef.current,
          signal,
        );
        if (result === 'failed') {
          pauseRemainingQueued('audio');
          break;
        }
      }
    },
    [pauseRemainingQueued, runAudio],
  );

  const start = useCallback(
    async (input: {
      kind: BatchKind;
      params: BatchParams;
      unitCredits: number;
      characters?: ScriptCharacter[];
      scenes?: ScriptScene[];
      videos?: PendingVideo[];
      audios?: PendingAudio[];
      document?: ScriptDocument;
    }) => {
      if (running) return;
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      persistKind.current = input.kind;
      persistParams.current = input.params;
      persistDocument.current = input.document ?? null;
      unitCreditsRef.current = input.unitCredits;
      pendingVideosRef.current = input.videos ?? [];
      pendingAudiosRef.current = input.audios ?? [];
      setPaused(false);

      const nextItems: BatchItemState[] =
        input.kind === 'characters'
          ? (input.characters ?? []).map((character) => ({
              kind: 'character',
              id: character.name,
              label: character.name,
              status: 'queued',
            }))
          : input.kind === 'scenes'
            ? (input.scenes ?? []).map((scene) => ({
                kind: 'scene',
                id: scene.heading,
                label: scene.heading,
                status: 'queued',
              }))
            : input.kind === 'audio'
              ? (input.audios ?? []).map((audio) => ({
                  kind: 'audio',
                  id: audio.key,
                  label: audio.heading,
                  status: 'queued',
                }))
              : (input.videos ?? []).map((video) => ({
                  kind: 'video',
                  id: video.key,
                  label: video.heading,
                  status: 'queued',
                }));

      setItems((current) => {
        const kept = current.filter((item) => {
          if (input.kind === 'characters') return item.kind !== 'character';
          if (input.kind === 'scenes') return item.kind !== 'scene';
          if (input.kind === 'audio') return item.kind !== 'audio';
          return item.kind !== 'video';
        });
        const merged = [...kept, ...nextItems];
        persist(merged);
        return merged;
      });
      setRunning(true);

      try {
        if (input.kind === 'characters' && input.characters) {
          await runImagePool(
            input.characters.map((character) => ({
              item: {
                kind: 'character',
                id: character.name,
                label: character.name,
                status: 'queued',
              },
              source: character,
            })),
            input.params,
            input.unitCredits,
            controller.signal,
          );
        } else if (input.kind === 'scenes' && input.scenes) {
          await runImagePool(
            input.scenes.map((scene) => ({
              item: {
                kind: 'scene',
                id: scene.heading,
                label: scene.heading,
                status: 'queued',
              },
              source: scene,
            })),
            input.params,
            input.unitCredits,
            controller.signal,
          );
        } else if (input.kind === 'videos' && input.videos && input.document) {
          await runVideoQueue(input.videos, controller.signal);
        } else if (input.kind === 'audio' && input.audios) {
          await runAudioQueue(input.audios, controller.signal);
        }
      } finally {
        if (abortRef.current === controller) {
          setRunning(false);
          persist(itemsRef.current);
        }
      }
    },
    [persist, runAudioQueue, runImagePool, runVideoQueue, running],
  );

  const retryImage = useCallback(
    async (kind: 'character' | 'scene', source: ScriptCharacter | ScriptScene) => {
      if (running) return;
      const id = kind === 'character' ? (source as ScriptCharacter).name : (source as ScriptScene).heading;
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      setRunning(true);
      try {
        const quote = await quoteForBatch(kind === 'character' ? 'characters' : 'scenes', persistParams.current, 1);
        unitCreditsRef.current = quote.unitCredits;
        await runImage(
          { kind, id, label: id, status: 'queued' },
          source,
          persistParams.current,
          quote.unitCredits,
          controller.signal,
        );
      } catch {
        patchItem(kind, id, { status: 'failed', error: 'quote_failed' });
      } finally {
        if (abortRef.current === controller) setRunning(false);
      }
    },
    [patchItem, runImage, running],
  );

  const resumeVideos = useCallback(async () => {
    const document = persistDocument.current;
    if (running || !document) return;
    const remaining = pendingVideosRef.current.filter((video) => {
      const item = itemsRef.current.find((row) => row.kind === 'video' && row.id === video.key);
      return item?.status === 'failed' || item?.status === 'paused' || item?.status === 'queued';
    });
    if (remaining.length === 0) return;
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setPaused(false);
    setItems((current) => {
      const ids = new Set(remaining.map((video) => video.key));
      const next = current.map((row) =>
        row.kind === 'video' && ids.has(row.id) && row.status !== 'succeeded'
          ? { ...row, status: 'queued' as const, error: undefined }
          : row,
      );
      persist(next);
      return next;
    });
    setRunning(true);
    try {
      try {
        const quote = await quoteForBatch('videos', persistParams.current, remaining.length);
        unitCreditsRef.current = quote.unitCredits;
      } catch {
        /* keep the last known unit price */
      }
      await runVideoQueue(remaining, controller.signal);
    } finally {
      if (abortRef.current === controller) setRunning(false);
    }
  }, [persist, runVideoQueue, running]);

  const resumeAudio = useCallback(async () => {
    if (running) return;
    const remaining = pendingAudiosRef.current.filter((audio) => {
      const item = itemsRef.current.find((row) => row.kind === 'audio' && row.id === audio.key);
      return item?.status === 'failed' || item?.status === 'paused' || item?.status === 'queued';
    });
    if (remaining.length === 0) return;
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setPaused(false);
    setItems((current) => {
      const ids = new Set(remaining.map((audio) => audio.key));
      const next = current.map((row) =>
        row.kind === 'audio' && ids.has(row.id) && row.status !== 'succeeded'
          ? { ...row, status: 'queued' as const, error: undefined }
          : row,
      );
      persist(next);
      return next;
    });
    setRunning(true);
    try {
      try {
        const quote = await quoteForBatch('audio', persistParams.current, remaining.length);
        unitCreditsRef.current = quote.unitCredits;
      } catch {
        /* keep the last known unit price */
      }
      await runAudioQueue(remaining, controller.signal);
    } finally {
      if (abortRef.current === controller) setRunning(false);
    }
  }, [persist, runAudioQueue, running]);

  /** The toolbar's single "重试并继续" button does not know which kind was
   * paused — `persistKind` (the last batch `start()` was called with)
   * decides which queue to resume. */
  const resumeQueue = useCallback(async () => {
    if (persistKind.current === 'audio') {
      await resumeAudio();
    } else {
      await resumeVideos();
    }
  }, [resumeAudio, resumeVideos]);

  const resumeAfterRefresh = useCallback(
    async (stored: StoredBatch, signal: AbortSignal) => {
      persistKind.current = stored.kind;
      persistParams.current = stored.params;
      persistDocument.current = stored.document;
      pendingVideosRef.current = stored.videos ?? [];
      pendingAudiosRef.current = stored.audios ?? [];
      unitCreditsRef.current = stored.unitCredits ?? 0;
      setItems(stored.items);
      setPaused(stored.items.some((item) => item.status === 'paused' || item.status === 'failed'));
      const inflight = stored.items.filter(
        (item) => item.jobId && (item.status === 'submitting' || item.status === 'running'),
      );
      const queued = stored.items.filter((item) => item.status === 'queued');
      if (inflight.length === 0 && queued.length === 0 && !stored.items.some((item) => item.status === 'paused')) {
        writeStore(episodeId, null);
        return;
      }
      setRunning(true);
      try {
        await Promise.all(
          inflight.map(async (item) => {
            if (!item.jobId) return;
            try {
              const job = await pollJob(item.jobId, signal);
              if (item.kind === 'video') {
                if (job.status === 'succeeded' && job.output_asset_id) {
                  bindingsRef.current = {
                    ...bindingsRef.current,
                    [item.id]: {
                      draftId: job.draft_id ?? item.draftId ?? '',
                      latestJobId: job.id,
                      outputAssetId: job.output_asset_id,
                    },
                  };
                  patchItem('video', item.id, { status: 'succeeded', error: undefined });
                  onVideoDraftCreatedRef.current();
                } else {
                  patchItem('video', item.id, {
                    status: 'failed',
                    error: job.failure_message || job.status,
                  });
                }
              } else if (item.kind === 'audio') {
                if (job.status === 'succeeded') {
                  patchItem('audio', item.id, { status: 'succeeded', error: undefined });
                  onLibraryChangedRef.current();
                } else {
                  patchItem('audio', item.id, {
                    status: 'failed',
                    error: job.failure_message || job.status,
                  });
                }
              } else {
                await finishImage(item, job);
              }
            } catch (error) {
              if (signal.aborted) return;
              patchItem(item.kind, item.id, {
                status: 'failed',
                error: error instanceof ApiError ? error.message : 'failed',
              });
            }
          }),
        );
      } finally {
        if (!signal.aborted) setRunning(false);
      }
    },
    [episodeId, finishImage, patchItem],
  );

  useEffect(() => {
    if (restored.current) return;
    restored.current = true;
    const stored = readStore(episodeId);
    if (!stored) return;
    const controller = new AbortController();
    abortRef.current = controller;
    // Restoring a batch's progress from `sessionStorage` on mount (a
    // one-time, `restored`-guarded resume of real in-flight jobs, not a
    // synchronous render-loop setState) — same shape as `updateLink`'s own
    // suppression above in `script-editor.tsx`.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void resumeAfterRefresh(stored, controller.signal);
    return () => controller.abort();
  }, [episodeId, resumeAfterRefresh]);

  useEffect(() => () => abortRef.current?.abort(), []);

  const itemByKey = useCallback(
    (kind: BatchItemKind, id: string) =>
      items.find((item) => item.kind === kind && item.id === id) ?? null,
    [items],
  );

  return {
    items,
    running,
    paused,
    itemByKey,
    start,
    retryImage,
    resumeQueue,
  };
}
