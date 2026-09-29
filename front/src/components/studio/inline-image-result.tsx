'use client';

import { useTranslations } from 'next-intl';
import { useEffect, useRef, useState } from 'react';

import { LiveThinking } from '@/components/ai/thinking-disclosure';
import { AwaitingInputPanel } from '@/components/job/awaiting-input-panel';
import { PromoteJobDialog } from '@/components/job/promote-job-dialog';
import {
  CHARACTER_VIEW_LABEL_KEY,
  STAGES,
  stageLabelKey,
  type Stage,
} from '@/components/job/job-stages';
import { jobStageState } from '@/components/job/job-stage-state';
import { jobOutputs } from '@/components/job/job-outputs';
import { DevicePreview } from '@/components/media/device-preview';
import { OutputGallery } from '@/components/media/output-gallery';
import { SaveCoverAsSkillDialog } from '@/components/studio/save-cover-as-skill-dialog';
import { Button } from '@/components/ui/button';
import { IconBranch, IconCheck, IconSparkle } from '@/components/ui/icons';
import { ErrorNotice } from '@/components/ui/primitives';
import { useToast } from '@/components/ui/toast';
import { useRouter } from '@/i18n/navigation';
import { api } from '@/lib/api/client';
import { isApiError } from '@/lib/api/errors';
import type { GenerationJob } from '@/lib/api/types';
import { cn } from '@/lib/cn';
import { loadAnime, useReducedMotion } from '@/lib/motion';
import { refreshAssetUrl, refreshJobOutputUrl } from '@/lib/refresh-media-src';
import type { StreamedEvent } from '@/lib/use-job-stream';

/**
 * Caps the media stage well below `DevicePreview`'s own remaining-viewport
 * sizing (see `useAvailableStage`), which otherwise grows a portrait
 * character/scene still to fill whatever viewport height is left below it —
 * fine for a standalone preview with nothing else to show, but here the
 * status line, the action row, and the version
 * history strip all sit directly below the stage in the same scroll
 * container. Without this cap, that whole action row lands just past the
 * fold on a fresh page load (e.g. resuming a draft from "最近草稿" → 编辑),
 * making it easy to miss even though it's technically reachable by
 * scrolling.
 */
const RESULT_STAGE_MAX_HEIGHT = 380;

const STAGE_POP_DURATION = 420;
const FUN_CAPTION_INTERVAL = 2200;
const FUN_CAPTION_COUNT = 2;

/**
 * The image studio's preview-area result — replaces the standalone
 * `/jobs/[jobId]` page for `text_to_image`/`image_to_image` so a generation
 * never navigates the user away from the studio (see `zaolang-frontend-ui`
 * invariant #16, extended by this feature: "image creation" now also never
 * leaves the studio to show progress or the result).
 *
 * Deliberately a smaller surface than `job-progress.tsx`: no event log
 * sidebar, no multi-view character breakdown, no "enter editor" (images
 * never do). What it keeps: the same stage mapping (`job-stages.ts`), the
 * same multi-output gallery, cancel, and the cover-asset "save as skill"
 * dialog — all of which the image studio's users still need without leaving
 * this page.
 */
export function InlineImageResult({
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
  returnTo,
  returnLinkKind,
  returnLinkLabel,
  fallbackLinkRefId,
  completionJob,
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
   * cinematic render — the new job (see `PromoteJobDialog`'s own doc
   * comment on why it's a separate job) becomes the studio's active one,
   * same shape as `onRetried`. */
  onPromoted: (job: GenerationJob) => void;
  /**
   * Set when this session started from a jump-out (`ImageGenerationStudio`'s
   * `returnTo`, from `/create/new`'s query). A terminal job — succeeded,
   * failed, or cancelled — gets a return button so the user is never stuck
   * here even on failure. Copy is `returnToCharacters` /
   * `returnToScenes` for the matching library path, otherwise
   * `returnToScript`.
   */
  returnTo?: string;
  returnLinkKind?: 'character' | 'scene';
  returnLinkLabel?: string;
  /** `targetCharacterId`/`targetSceneId` as currently selected in the studio
   * — used only if the job itself never got linked (e.g. `auto_attach_asset`
   * was off), so the link the user was clearly working towards still makes
   * it back instead of forcing a bare, unlinked return. */
  fallbackLinkRefId?: string;
  /**
   * A historical "补全侧面/背面" completion job supplementing `job`, if
   * any — resolved by `ImageGenerationStudio` from the draft's full job
   * list (`findCompletionJobFor`). The studio no longer offers a new
   * completion; this only merges already-produced side/back outputs into
   * the gallery so an older draft still shows every angle.
   */
  completionJob?: GenerationJob | null;
}) {
  const t = useTranslations('jobPage');
  const tJob = useTranslations('job');
  const tStudio = useTranslations('remixPage');
  const tCharacters = useTranslations('characters');
  const { notify } = useToast();
  const router = useRouter();

  const [retrying, setRetrying] = useState(false);
  const [savingCoverSkillOpen, setSavingCoverSkillOpen] = useState(false);
  const [promoteOpen, setPromoteOpen] = useState(false);

  const { reached, displayStage, finished, awaitingInput, reachedKey } = jobStageState(
    job.status,
    events,
  );
  const latestEvent = events[events.length - 1];
  const showAwaitingPanel = awaitingInput && !job.cancel_requested;

  // Ports `job-progress.tsx`'s stage-dot pop animation so image creation's
  // inline progress view isn't limited to a bare percentage + label.
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

  // A small rotating set of playful captions per stage, replacing the flat
  // static stage label while a job is still in flight. Reset during render
  // (not in an effect) when the stage changes — the recommended pattern for
  // "adjusting state when a prop changes" — so only the interval tick itself
  // needs an effect.
  const [captionIndex, setCaptionIndex] = useState(0);
  const [captionStage, setCaptionStage] = useState(displayStage);
  if (captionStage !== displayStage) {
    setCaptionStage(displayStage);
    setCaptionIndex(0);
  }
  useEffect(() => {
    if (reduced || finished) return;
    const id = window.setInterval(() => {
      setCaptionIndex((index) => (index + 1) % FUN_CAPTION_COUNT);
    }, FUN_CAPTION_INTERVAL);
    return () => window.clearInterval(id);
  }, [displayStage, reduced, finished]);

  // `job`'s own output(s) — front view only, or every view for a native
  // multi-view character job that never needed a separate completion job.
  const { urls: jobUrls, assetIds: jobAssetIds } = jobOutputs(job);
  const jobViews = job.character_views ?? null;
  const jobLabels: (string | null)[] =
    jobViews && jobViews.length === jobUrls.length
      ? jobViews.map((view) => tCharacters(CHARACTER_VIEW_LABEL_KEY[view] ?? 'viewFront'))
      : jobUrls.map(() => null);

  // Historical side/back outputs, appended after `job`'s own — only once
  // that completion job has succeeded. The studio no longer starts a new
  // completion from this result.
  const completionSucceeded = completionJob?.status === 'succeeded';
  const completionUrls = completionSucceeded ? (completionJob?.output_urls ?? []) : [];
  const completionAssetIds = completionSucceeded ? (completionJob?.output_asset_ids ?? []) : [];
  const completionViews = completionSucceeded ? (completionJob?.character_views ?? []) : [];
  const completionLabels: (string | null)[] =
    completionViews.length === completionUrls.length
      ? completionViews.map((view) => tCharacters(CHARACTER_VIEW_LABEL_KEY[view] ?? 'viewSide'))
      : completionUrls.map(() => null);

  const galleryUrls = [...jobUrls, ...completionUrls];
  const galleryAssetIds = [...jobAssetIds, ...completionAssetIds];
  const galleryLabels = [...jobLabels, ...completionLabels];
  const hasMultipleOutputs = galleryUrls.length > 1;

  const refreshOutputSrc = () =>
    job.output_asset_id ? refreshAssetUrl(job.output_asset_id) : refreshJobOutputUrl(job.id);

  // Silently carries the fresh link back — matching `ScriptLinkPicker`'s own
  // click-to-link behaviour, no confirmation dialog either direction (see
  // the plan's "补充建议" #5). Falls back to `fallbackLinkRefId` only for a
  // succeeded job the backend never linked itself (`auto_attach_asset` off);
  // failed/cancelled always return bare, since there is nothing to link.
  const returnLinkRefId =
    job.status === 'succeeded'
      ? (job.linked_character_id ?? job.linked_scene_id ?? fallbackLinkRefId ?? null)
      : null;
  const returnHref =
    returnTo && returnLinkRefId && returnLinkKind && returnLinkLabel
      ? `${returnTo}?${new URLSearchParams({
          linkKind: returnLinkKind,
          linkLabel: returnLinkLabel,
          linkRefId: returnLinkRefId,
        }).toString()}`
      : returnTo;

  const canUseAsReference = job.status === 'succeeded' && Boolean(job.output_asset_id);
  const canSaveCoverSkill =
    job.status === 'succeeded' && job.asset_kind === 'cover' && Boolean(job.output_asset_id);
  const canPromote = job.status === 'succeeded' && job.quality_tier === 'preview';

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

  return (
    <div className="flex flex-col gap-3">
      {hasMultipleOutputs ? (
        <OutputGallery
          urls={galleryUrls}
          assetIds={galleryAssetIds}
          mediaType={job.output_media_type ?? 'image'}
          title={t('title')}
          labels={galleryLabels}
          itemLabel={(index, total) => t('outputItemLabel', { index, total })}
          maxHeight={RESULT_STAGE_MAX_HEIGHT}
        />
      ) : job.output_url ? (
        <DevicePreview
          src={job.output_url}
          title={t('title')}
          mediaType="image"
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
              <p
                aria-live="polite"
                className="tabular text-4xl font-semibold tracking-tight text-text"
              >
                {job.progress}%
              </p>
              <p aria-live="polite" className="text-sm text-text">
                {t(`funCaptions.${displayStage}.${captionIndex}`)}
              </p>
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

      {/* `job`/`completionJob` are both plain `GenerationJob`s that can
        suspend at `awaiting_input`. A job with no output already renders
        the panel in the preview slot above; keep a second copy only when
        there is already a result to show, or when the independent
        completion job (补全侧面/背面) is the one waiting. */}
      {showAwaitingPanel && (hasMultipleOutputs || job.output_url) ? (
        <AwaitingInputPanel key={job.id} jobId={job.id} />
      ) : null}
      {completionJob?.status === 'awaiting_input' && !completionJob.cancel_requested ? (
        <AwaitingInputPanel key={completionJob.id} jobId={completionJob.id} />
      ) : null}

      <div className="flex flex-wrap items-center gap-2">
        {finished && returnHref ? (
          <Button variant="primary" size="sm" onClick={() => router.push(returnHref)}>
            {tStudio(
              returnTo === '/create/characters'
                ? 'returnToCharacters'
                : returnTo === '/create/scenes'
                  ? 'returnToScenes'
                  : 'returnToScript',
            )}
          </Button>
        ) : null}
        {canUseAsReference ? (
          <Button
            variant="secondary"
            size="sm"
            icon={<IconBranch className="size-4" />}
            onClick={() => onUseAsReference(job)}
          >
            {tStudio('useAsReference')}
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
