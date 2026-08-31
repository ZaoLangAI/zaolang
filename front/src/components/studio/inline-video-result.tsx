'use client';

import { useLocale, useTranslations } from 'next-intl';
import { useEffect, useRef, useState } from 'react';

import { LiveThinking } from '@/components/ai/thinking-disclosure';
import { useSession } from '@/components/auth/session-provider';
import { AwaitingInputPanel } from '@/components/job/awaiting-input-panel';
import { PromoteJobDialog } from '@/components/job/promote-job-dialog';
import {
  STAGE_FOR_EVENT,
  STAGES,
  stageLabelKey,
  type Stage,
} from '@/components/job/job-stages';
import { DevicePreview } from '@/components/media/device-preview';
import { SaveCoverAsSkillDialog } from '@/components/studio/save-cover-as-skill-dialog';
import { Button } from '@/components/ui/button';
import { IconBranch, IconCheck, IconSparkle } from '@/components/ui/icons';
import { ErrorNotice } from '@/components/ui/primitives';
import { useToast } from '@/components/ui/toast';
import { createCutFromJob } from '@/features/editor/from-job';
import { useRouter } from '@/i18n/navigation';
import type { Locale } from '@/i18n/routing';
import { api } from '@/lib/api/client';
import { isApiError } from '@/lib/api/errors';
import type { GenerationJob } from '@/lib/api/types';
import { cn } from '@/lib/cn';
import { loadAnime, useReducedMotion } from '@/lib/motion';
import { refreshAssetUrl, refreshJobOutputUrl } from '@/lib/refresh-media-src';
import type { StreamedEvent } from '@/lib/use-job-stream';

const RESULT_STAGE_MAX_HEIGHT = 380;
const STAGE_POP_DURATION = 420;

/**
 * The video studio's preview-area result — replaces the standalone
 * `/jobs/[jobId]` page for `text_to_video`/`image_to_video`/`video_to_video`
 * so a generation never navigates the user away from the studio, extending
 * `inline-image-result.tsx`'s architecture to video creation (see
 * `zaolang-frontend-ui` invariant #19).
 *
 * A smaller sibling of `job-progress.tsx`/`inline-image-result.tsx`: no
 * event-log sidebar (that stays `job-progress.tsx`-only), no character-
 * completion surface (video has none), no multi-output gallery (a video job
 * only ever produces one output — see `zaolang-generation-jobs` invariant
 * #20). What it keeps: the same stage mapping (`job-stages.ts`), cancel/
 * retry/promote, the cover-asset "另存为可分享技能" dialog (now keyed off
 * `video_asset_kind === 'cover_video'` instead of image's `asset_kind ===
 * 'cover'`), and — video-only — "进入剪辑" (`job-progress.tsx`'s own
 * `canEnterEditor`/`enterEditor`, ported here since this result no longer
 * has a standalone job page to fall back on).
 */
export function InlineVideoResult({
  job,
  events,
  connected,
  reconnecting,
  liveThinking,
  draftId,
  cancelling,
  onCancel,
  onUseAsReference,
  onRetried,
  onPromoted,
}: {
  job: GenerationJob;
  events: StreamedEvent[];
  connected: boolean;
  reconnecting: boolean;
  liveThinking?: string;
  draftId: string | null;
  cancelling: boolean;
  onCancel: () => void;
  onUseAsReference: (job: GenerationJob) => void;
  onRetried: (job: GenerationJob) => void;
  /** A preview-tier `job` succeeded and got upgraded to a full standard/
   * cinematic render — the new job becomes the studio's active one, same
   * shape as `onRetried`. */
  onPromoted: (job: GenerationJob) => void;
}) {
  const t = useTranslations('jobPage');
  const tJob = useTranslations('job');
  const tEditor = useTranslations('editor');
  const tStudio = useTranslations('remixPage');
  const { notify } = useToast();
  const router = useRouter();
  const locale = useLocale() as Locale;
  const { user } = useSession();

  const [retrying, setRetrying] = useState(false);
  const [savingCoverSkillOpen, setSavingCoverSkillOpen] = useState(false);
  const [promoteOpen, setPromoteOpen] = useState(false);
  const [openingEditor, setOpeningEditor] = useState(false);

  const reached = new Set<Stage>();
  for (const event of events) {
    const stage = STAGE_FOR_EVENT[event.event_type];
    if (stage) reached.add(stage);
  }
  if (job.status === 'succeeded') for (const stage of STAGES) reached.add(stage);

  const activeIndex = STAGES.findIndex((stage) => !reached.has(stage));
  const finished = ['succeeded', 'failed', 'cancelled', 'expired'].includes(job.status);
  const latestEvent = events[events.length - 1];
  const awaitingInput = job.status === 'awaiting_input';
  const showAwaitingPanel = awaitingInput && !job.cancel_requested;
  const displayStage: Stage = awaitingInput
    ? 'planning'
    : finished && job.status !== 'succeeded'
      ? ([...STAGES].reverse().find((stage) => reached.has(stage)) ?? 'queued')
      : (STAGES[activeIndex] ?? 'done');
  const reachedKey = STAGES.filter((stage) => reached.has(stage)).join(',');

  const reduced = useReducedMotion();
  const dotRefs = useRef<Partial<Record<Stage, HTMLSpanElement | null>>>({});
  const previousReachedRef = useRef<Set<Stage>>(new Set());
  const stageAnimationReady = useRef(false);

  useEffect(() => {
    const previous = previousReachedRef.current;
    previousReachedRef.current = reached;
    if (!stageAnimationReady.current) {
      stageAnimationReady.current = true;
      return;
    }
    if (reduced) return;
    const newlyDone = STAGES.filter((stage) => reached.has(stage) && !previous.has(stage));
    if (newlyDone.length === 0) return;
    loadAnime().then(({ animate }) => {
      for (const stage of newlyDone) {
        const node = dotRefs.current[stage];
        if (node)
          animate(node, { scale: [1, 1.3, 1], duration: STAGE_POP_DURATION, ease: 'outQuad' });
      }
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reachedKey, reduced]);

  const refreshOutputSrc = () =>
    job.output_asset_id ? refreshAssetUrl(job.output_asset_id) : refreshJobOutputUrl(job.id);

  const canUseAsReference = job.status === 'succeeded' && Boolean(job.output_asset_id);
  const canSaveCoverSkill =
    job.status === 'succeeded' &&
    job.video_asset_kind === 'cover_video' &&
    Boolean(job.output_asset_id);
  const canPromote = job.status === 'succeeded' && job.quality_tier === 'preview';
  const canEnterEditor =
    job.status === 'succeeded' &&
    (job.operation === 'text_to_video' ||
      job.operation === 'image_to_video' ||
      job.operation === 'video_to_video');
  // Reads the flag straight off `/v1/auth/me` rather than probing a series
  // list — `undefined` (session not loaded yet) fails open, matching
  // `job-progress.tsx`'s own stance.
  const showEnterEditor = canEnterEditor && (user?.features.web_editor ?? true);

  const retry = async () => {
    setRetrying(true);
    try {
      const next = await api.post<GenerationJob>(`/v1/generation-jobs/${job.id}/retry`);
      onRetried(next);
    } catch (error) {
      notify(isApiError(error) ? error.message : t('cancelFailed'), 'error');
    } finally {
      setRetrying(false);
    }
  };

  const enterEditor = async () => {
    setOpeningEditor(true);
    const tab = window.open('', '_blank', 'noopener,noreferrer');
    try {
      const cut = await createCutFromJob(job.id);
      const draftQuery = job.draft_id ? `?draftId=${encodeURIComponent(job.draft_id)}` : '';
      const path = `/studio-editor/${cut.id}${draftQuery}`;
      if (tab) tab.location.href = `/${locale}${path}`;
      else router.push(path);
    } catch (error) {
      tab?.close();
      if (isApiError(error) && error.isNotFound && job.draft_id) {
        router.push(`/publish/${job.draft_id}`);
        return;
      }
      notify(isApiError(error) ? error.message : tEditor('commandFailed'), 'error');
    } finally {
      setOpeningEditor(false);
    }
  };

  return (
    <div className="flex flex-col gap-3">
      {job.output_url ? (
        <DevicePreview
          src={job.output_url}
          title={t('title')}
          mediaType="video"
          refreshSrc={refreshOutputSrc}
          maxHeight={RESULT_STAGE_MAX_HEIGHT}
        />
      ) : showAwaitingPanel ? (
        <AwaitingInputPanel key={job.id} jobId={job.id} />
      ) : (
        <div className="relative aspect-video overflow-hidden rounded-[var(--radius-md)] border border-border bg-surface-soft">
          <div className="absolute inset-0 grid place-items-center px-6">
            <div className="flex flex-col items-center gap-2 text-center">
              <IconSparkle
                className={cn('size-5 text-amber', !reduced && !finished && 'animate-pulse')}
              />
              <p aria-live="polite" className="tabular text-4xl font-semibold tracking-tight text-text">
                {job.progress}%
              </p>
              <p className="text-sm text-text">{t(stageLabelKey(displayStage, job.operation))}</p>
              {latestEvent?.message ? (
                <p className="max-w-md text-sm text-muted">{latestEvent.message}</p>
              ) : null}
              {!finished ? (
                <LiveThinking
                  thinking={liveThinking ?? ''}
                  label={t('thinkingLive')}
                  className="max-h-28 overflow-y-auto"
                />
              ) : null}
              <ol className="mt-1 flex flex-wrap justify-center gap-x-4 gap-y-1.5">
                {STAGES.map((stage) => {
                  const done = awaitingInput && stage === 'planning' ? false : reached.has(stage);
                  const active = awaitingInput
                    ? stage === 'planning'
                    : stage === displayStage && !finished;
                  return (
                    <li
                      key={stage}
                      aria-current={active ? 'step' : undefined}
                      title={t(stageLabelKey(stage, job.operation))}
                      className="flex items-center gap-1"
                    >
                      <span
                        ref={(node) => {
                          dotRefs.current[stage] = node;
                        }}
                        aria-label={t(stageLabelKey(stage, job.operation))}
                        className={cn(
                          'grid size-3.5 place-items-center rounded-full border',
                          done
                            ? 'border-success bg-success/15'
                            : active
                              ? 'border-primary'
                              : 'border-border',
                        )}
                      >
                        {done ? <IconCheck className="size-2" /> : null}
                      </span>
                    </li>
                  );
                })}
              </ol>
            </div>
          </div>
          <div className="absolute inset-x-0 bottom-0 h-1.5 overflow-hidden bg-track">
            <div
              className="h-full rounded-full bg-primary transition-[width] duration-500 ease-out"
              style={{ width: `${job.progress}%` }}
            />
          </div>
        </div>
      )}

      {job.status !== 'succeeded' ? (
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span className={cn('font-medium', statusColor(job.status))}>{tJob(job.status)}</span>
          {reconnecting ? (
            <span role="status" className="text-amber">
              {tJob('reconnecting')}
            </span>
          ) : connected && !finished ? (
            <span role="status" className="text-success">
              {t('liveUpdating')}
            </span>
          ) : null}
          {job.cancel_requested && !finished ? (
            <span className="text-muted">{t('cancellingHint')}</span>
          ) : null}
        </div>
      ) : null}

      {!finished ? (
        <div className="flex justify-center">
          <Button
            variant="ghost"
            size="sm"
            onClick={onCancel}
            loading={cancelling}
            disabled={job.cancel_requested}
          >
            {job.cancel_requested ? tJob('cancelRequested') : tJob('cancel')}
          </Button>
        </div>
      ) : null}

      {job.status === 'failed' ? (
        <ErrorNotice
          title={job.failure_message ?? t('failedTitle')}
          detail={`${t('failedHint')}${job.failure_code ? ` · ${tJob('errorCode', { code: job.failure_code })}` : ''}`}
        />
      ) : null}
      {job.status === 'cancelled' ? (
        <ErrorNotice title={t('cancelledTitle')} detail={t('failedHint')} />
      ) : null}

      {showAwaitingPanel && job.output_url ? <AwaitingInputPanel key={job.id} jobId={job.id} /> : null}

      <div className="flex flex-wrap items-center gap-2">
        {showEnterEditor ? (
          <Button size="sm" onClick={() => void enterEditor()} loading={openingEditor}>
            {tJob('enterEditor')}
          </Button>
        ) : null}
        {canUseAsReference ? (
          <Button
            variant="secondary"
            size="sm"
            icon={<IconBranch className="size-4" />}
            onClick={() => onUseAsReference(job)}
          >
            {tStudio('useVideoAsReference')}
          </Button>
        ) : null}
        {job.status === 'succeeded' && draftId ? (
          <Button variant="secondary" size="sm" onClick={() => router.push(`/publish/${draftId}`)}>
            {tJob('publish')}
          </Button>
        ) : null}
        {canSaveCoverSkill ? (
          <Button variant="secondary" size="sm" onClick={() => setSavingCoverSkillOpen(true)}>
            {t('saveCoverSkill')}
          </Button>
        ) : null}
        {canPromote ? (
          <Button variant="secondary" size="sm" onClick={() => setPromoteOpen(true)}>
            {t('promote')}
          </Button>
        ) : null}
        {job.status === 'failed' || job.status === 'cancelled' ? (
          <Button variant="secondary" size="sm" loading={retrying} onClick={() => void retry()}>
            {tJob('retry')}
          </Button>
        ) : null}
      </div>

      <SaveCoverAsSkillDialog
        open={savingCoverSkillOpen}
        onClose={() => setSavingCoverSkillOpen(false)}
        outputAssetId={job.output_asset_id}
      />

      <PromoteJobDialog
        open={promoteOpen}
        onClose={() => setPromoteOpen(false)}
        job={job}
        onPromoted={onPromoted}
      />
    </div>
  );
}

function statusColor(status: string): string {
  if (status === 'succeeded') return 'text-success';
  if (status === 'failed') return 'text-danger';
  if (status === 'cancelled' || status === 'expired') return 'text-amber';
  return 'text-text';
}
