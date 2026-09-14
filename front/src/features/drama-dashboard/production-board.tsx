'use client';

import { useLocale, useTranslations } from 'next-intl';
import { useCallback, useEffect, useRef, useState } from 'react';

import { useSession } from '@/components/auth/session-provider';
import { useNotificationCenter } from '@/components/notifications/notification-center-provider';
import { SectionHeading } from '@/components/ui/primitives';
import type { ScriptDocument } from '@/features/script/api';
import { dubbedDialogueKeys, indexBreakpointVideos } from '@/features/script/script-breakpoint';
import type { Locale } from '@/i18n/routing';
import { api } from '@/lib/api/client';
import type { Draft, GenerationJob } from '@/lib/api/types';
import { cn } from '@/lib/cn';
import { formatDuration, formatNumber } from '@/lib/format';

import {
  creditsSpent,
  currentProductionStage,
  episodeProductionStages,
  productionShots,
  takeCount,
  unmatchedVideoDraftCount,
  type ProductionStageKey,
  type ShotStatus,
} from './production-stages';

const STAGE_LABEL_KEYS = {
  script: 'productionStageScript',
  characters: 'productionStageCharacters',
  scenes: 'productionStageScenes',
  shots: 'productionStageShots',
  voice: 'productionStageVoice',
  edit: 'productionStageEdit',
  export: 'productionStageExport',
  publish: 'productionStagePublish',
} as const satisfies Record<ProductionStageKey, string>;

const SHOT_STATUS_KEYS = {
  ready: 'productionShotReady',
  generating: 'productionShotGenerating',
  failed: 'productionShotFailed',
  missing: 'productionShotMissing',
} as const satisfies Record<ShotStatus, string>;

const SHOT_STATUS_CLASSES: Record<ShotStatus, string> = {
  ready: 'border-success/40 bg-success/10',
  generating: 'border-primary/40 bg-primary/10 motion-safe:animate-pulse',
  failed: 'border-danger/40 bg-danger/10',
  missing: 'border-dashed border-border bg-surface-soft',
};

// Card width is proportional to the generated length; a segment with no
// video yet gets a fixed-width dashed frame rather than an invented length.
const PX_PER_SECOND = 10;
const MIN_CARD_PX = 64;
const MAX_CARD_PX = 200;
const UNKNOWN_CARD_PX = 88;

function listDraftJobs(draftId: string): Promise<GenerationJob[]> {
  return api
    .get<{ items: GenerationJob[] }>(`/v1/generation-jobs?draft_id=${encodeURIComponent(draftId)}`)
    .then((page) => page.items);
}

/**
 * The episode's production board: a stage track from script to publish, a
 * duration-proportional strip of the script's segments, and what the viewer
 * has spent here. Built only from data the episode workspace already has
 * plus each segment draft's own job list; it never opens a stream of its own
 * — a notification naming one of these drafts refetches just that draft.
 */
export function ProductionBoard({
  script,
  hasScript,
  drafts,
  cutCount,
  exportStatuses,
  published,
  onDraftUpdated,
}: {
  script: ScriptDocument | null;
  hasScript: boolean;
  /** Every draft linked to the episode (video, voice and image alike). */
  drafts: Draft[];
  cutCount: number;
  exportStatuses: string[];
  published: boolean;
  /** Refetch one draft after a notification says its generation moved. */
  onDraftUpdated: (draftId: string) => void;
}) {
  const t = useTranslations('editor');
  const locale = useLocale() as Locale;
  const { user } = useSession();
  const { recent } = useNotificationCenter();
  const [jobsByDraft, setJobsByDraft] = useState<Record<string, GenerationJob[]>>({});

  const loadJobs = useCallback((draftIds: string[]) => {
    void Promise.all(
      draftIds.map((id) =>
        listDraftJobs(id)
          .then((items) => [id, items] as const)
          .catch(() => [id, [] as GenerationJob[]] as const),
      ),
    ).then((entries) => {
      setJobsByDraft((current) => ({ ...current, ...Object.fromEntries(entries) }));
    });
  }, []);

  // Keyed by the id list's contents: `drafts` is a fresh array every render.
  const trackedIds = drafts
    .filter((draft) => typeof draft.params?.link_breakpoint_key === 'string')
    .map((draft) => draft.id);
  const trackedKey = trackedIds.join(',');
  useEffect(() => {
    if (trackedKey) loadJobs(trackedKey.split(','));
  }, [trackedKey, loadJobs]);

  // Only notifications that arrive after mount count; the one already on
  // top when the page opened is old news.
  const latest = recent[0];
  const handledNotificationId = useRef(latest?.id ?? null);
  useEffect(() => {
    if (!latest || latest.id === handledNotificationId.current) return;
    handledNotificationId.current = latest.id;
    const draftId = latest.payload?.draft_id;
    if (typeof draftId !== 'string' || !trackedKey.split(',').includes(draftId)) return;
    loadJobs([draftId]);
    onDraftUpdated(draftId);
  }, [latest, trackedKey, loadJobs, onDraftUpdated]);

  const scenes = script?.scenes ?? [];
  const bindings = indexBreakpointVideos(drafts, scenes);
  const stages = episodeProductionStages({
    hasScript,
    script,
    bindings,
    dubbedKeys: dubbedDialogueKeys(drafts),
    cutCount,
    exportStatuses,
    published,
  });
  const current = currentProductionStage(stages);
  const draftsById = Object.fromEntries(drafts.map((draft) => [draft.id, draft]));
  const shots = script && hasScript ? productionShots(script, bindings, draftsById, jobsByDraft) : [];
  const unmatched = script && hasScript ? unmatchedVideoDraftCount(script, drafts) : 0;
  const spent = creditsSpent(Object.values(jobsByDraft).flat());
  const available = user?.available_credits;

  return (
    <section className="flex flex-col gap-4 rounded-[var(--radius-md)] border border-border bg-surface p-4">
      <SectionHeading title={t('productionBoardTitle')} description={t('productionBoardHint')} />
      <ol
        aria-label={t('productionStagesLabel')}
        className="flex flex-wrap items-center gap-x-1.5 gap-y-2 text-xs"
      >
        {stages.map((stage, index) => {
          const isCurrent = stage.key === current;
          return (
            <li
              key={stage.key}
              className="flex items-center gap-1.5"
              aria-current={isCurrent ? 'step' : undefined}
            >
              {index > 0 ? <span aria-hidden="true" className="h-px w-3 bg-border" /> : null}
              <span
                aria-hidden="true"
                className={cn(
                  'size-2 rounded-full',
                  stage.state === 'done'
                    ? 'bg-success'
                    : stage.state === 'active'
                      ? 'bg-primary'
                      : 'bg-border',
                  isCurrent && 'ring-2 ring-primary/30',
                )}
              />
              <span className={cn(isCurrent ? 'font-medium text-text' : 'text-muted')}>
                {t(STAGE_LABEL_KEYS[stage.key])}
                {stage.total ? (
                  <span className="ml-1 tabular-nums">
                    {t('productionStageCount', { done: stage.done ?? 0, total: stage.total })}
                  </span>
                ) : null}
              </span>
            </li>
          );
        })}
      </ol>

      {script && hasScript && shots.length === 0 ? (
        <p className="text-xs text-muted">{t('productionShotsEmpty')}</p>
      ) : null}
      {shots.length > 0 ? (
        <div className="overflow-x-auto pb-1">
          <ol aria-label={t('productionShotsLabel')} className="flex min-w-max items-stretch gap-1.5">
            {shots.map((shot) => {
              const width =
                shot.durationSeconds == null
                  ? UNKNOWN_CARD_PX
                  : Math.min(MAX_CARD_PX, Math.max(MIN_CARD_PX, shot.durationSeconds * PX_PER_SECOND));
              const takes = shot.draftId ? takeCount(jobsByDraft[shot.draftId] ?? []) : 0;
              const statusLabel = t(SHOT_STATUS_KEYS[shot.status]);
              return (
                <li
                  key={shot.key}
                  style={{ width }}
                  title={`${shot.heading} · ${statusLabel}`}
                  className={cn(
                    'flex h-16 shrink-0 flex-col justify-between rounded-[var(--radius-sm)] border px-2 py-1.5 text-[11px]',
                    SHOT_STATUS_CLASSES[shot.status],
                  )}
                >
                  <span className="font-medium tabular-nums">{shot.label}</span>
                  <span className="flex items-center justify-between gap-1 text-muted">
                    <span className="truncate tabular-nums">
                      {shot.durationSeconds == null
                        ? t('productionDurationUnknown')
                        : formatDuration(shot.durationSeconds)}
                    </span>
                    {takes > 0 ? (
                      <span className="tabular-nums">{t('productionTakes', { count: takes })}</span>
                    ) : null}
                  </span>
                  <span className="sr-only">{statusLabel}</span>
                </li>
              );
            })}
          </ol>
        </div>
      ) : null}

      {unmatched > 0 || available != null ? (
        <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted">
          {unmatched > 0 ? (
            <span className="text-amber">{t('productionUnmatched', { count: unmatched })}</span>
          ) : (
            <span />
          )}
          {available != null ? (
            <span className="tabular-nums">
              {t('productionSpentMeter', {
                spent: formatNumber(spent, locale),
                available: formatNumber(available, locale),
              })}
            </span>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
