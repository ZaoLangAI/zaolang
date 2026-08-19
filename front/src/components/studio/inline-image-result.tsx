'use client';

import { useTranslations } from 'next-intl';
import { useState } from 'react';

import { AwaitingInputPanel } from '@/components/job/awaiting-input-panel';
import {
  CHARACTER_VIEW_LABEL_KEY,
  STAGE_FOR_EVENT,
  STAGES,
  stageLabelKey,
  type Stage,
} from '@/components/job/job-stages';
import { AccessPriceField } from '@/components/marketplace/access-price-field';
import { DevicePreview } from '@/components/media/device-preview';
import { OutputGallery } from '@/components/media/output-gallery';
import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { TextArea, TextInput } from '@/components/ui/field';
import { IconBranch, IconSparkle } from '@/components/ui/icons';
import { ErrorNotice } from '@/components/ui/primitives';
import { useToast } from '@/components/ui/toast';
import { useRouter } from '@/i18n/navigation';
import { api } from '@/lib/api/client';
import { isApiError } from '@/lib/api/errors';
import type { CreationSkillDetail, GenerationJob } from '@/lib/api/types';
import { cn } from '@/lib/cn';
import { refreshAssetUrl, refreshJobOutputUrl } from '@/lib/refresh-media-src';
import type { StreamedEvent } from '@/lib/use-job-stream';

/**
 * Caps the media stage well below `DevicePreview`'s own remaining-viewport
 * sizing (see `useAvailableStage`), which otherwise grows a portrait
 * character/scene still to fill whatever viewport height is left below it —
 * fine for a standalone preview with nothing else to show, but here the
 * status line, the action row (including "补全侧面/背面"), and the version
 * history strip all sit directly below the stage in the same scroll
 * container. Without this cap, that whole action row lands just past the
 * fold on a fresh page load (e.g. resuming a draft from "最近草稿" → 编辑),
 * making it easy to miss even though it's technically reachable by
 * scrolling.
 */
const RESULT_STAGE_MAX_HEIGHT = 380;

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
  draftId,
  cancelling,
  onCancel,
  onUseAsReference,
  onRetried,
  returnTo,
  returnLinkKind,
  returnLinkLabel,
  fallbackLinkRefId,
  completionJob,
  canCompleteCharacterViews,
  completingCharacterViews,
  onCompleteCharacterViews,
}: {
  job: GenerationJob;
  events: StreamedEvent[];
  connected: boolean;
  reconnecting: boolean;
  draftId: string | null;
  cancelling: boolean;
  onCancel: () => void;
  onUseAsReference: (job: GenerationJob) => void;
  onRetried: (job: GenerationJob) => void;
  /**
   * Set only when this session started from the script studio's "生成角色图
   * /场景图" jump-out (`ImageGenerationStudio`'s own `returnTo` prop,
   * carried from `/create/new`'s query string). When set, a terminal job —
   * succeeded, failed, or cancelled — gets a "返回文案创作" button so the
   * user is never stuck here even on failure (see the plan's "补充建议" #4).
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
   * The "补全侧面/背面" completion job supplementing `job`, if any —
   * resolved by `ImageGenerationStudio` from the draft's full job list
   * (`findCompletionJobFor`), not a version of its own (see
   * `GenerationVersionHistory`). Once it has succeeded, its outputs are
   * merged into `job`'s own gallery below — front, then side, then back,
   * all one `OutputGallery` carousel — so a completed version still shows
   * as a single card in the version history while its preview lets the
   * user flip through all three angles.
   */
  completionJob?: GenerationJob | null;
  /**
   * True when `job` is a succeeded, single-view `asset_kind: 'character'`
   * job (the front view) whose target character is still missing a side or
   * back reference — computed by `ImageGenerationStudio` (it alone knows
   * the character's current reference-asset state), not derived from `job`
   * alone. Shows the "补全侧面/背面" button below instead of forcing the
   * user out to the character library page for it.
   */
  canCompleteCharacterViews?: boolean;
  /** Whether `completionJob` is still in flight (submitting or not yet
   * terminal) — independent of `job`'s own state. */
  completingCharacterViews?: boolean;
  onCompleteCharacterViews?: () => void;
}) {
  const t = useTranslations('jobPage');
  const tJob = useTranslations('job');
  const tStudio = useTranslations('remixPage');
  const tSkills = useTranslations('skillLibrary');
  const tActions = useTranslations('actions');
  const tCharacters = useTranslations('characters');
  const { notify } = useToast();
  const router = useRouter();

  const [retrying, setRetrying] = useState(false);
  const [savingCoverSkillOpen, setSavingCoverSkillOpen] = useState(false);
  const [coverSkillTitle, setCoverSkillTitle] = useState('');
  const [coverSkillDescription, setCoverSkillDescription] = useState('');
  const [coverSkillCredits, setCoverSkillCredits] = useState(0);
  const [coverSkillBusy, setCoverSkillBusy] = useState(false);

  const reached = new Set<Stage>();
  for (const event of events) {
    const stage = STAGE_FOR_EVENT[event.event_type];
    if (stage) reached.add(stage);
  }
  if (job.status === 'succeeded') for (const stage of STAGES) reached.add(stage);

  const activeIndex = STAGES.findIndex((stage) => !reached.has(stage));
  const finished = ['succeeded', 'failed', 'cancelled', 'expired'].includes(job.status);
  const latestEvent = events[events.length - 1];
  const displayStage: Stage =
    finished && job.status !== 'succeeded'
      ? ([...STAGES].reverse().find((stage) => reached.has(stage)) ?? 'queued')
      : (STAGES[activeIndex] ?? 'done');

  // `job`'s own output(s) — front view only, or every view for a native
  // multi-view character job that never needed a separate completion job.
  const jobUrls = job.output_urls?.length ? job.output_urls : job.output_url ? [job.output_url] : [];
  const jobAssetIds = job.output_asset_ids?.length
    ? job.output_asset_ids
    : job.output_asset_id
      ? [job.output_asset_id]
      : [];
  const jobViews = job.character_views ?? null;
  const jobLabels: (string | null)[] =
    jobViews && jobViews.length === jobUrls.length
      ? jobViews.map((view) => tCharacters(CHARACTER_VIEW_LABEL_KEY[view] ?? 'viewFront'))
      : jobUrls.map(() => null);

  // The completion job's side/back outputs, appended after `job`'s own —
  // only once it has actually succeeded; still in flight, it has nothing
  // to show yet and the button below carries the "补全侧面/背面" progress
  // state instead.
  const completionSucceeded = completionJob?.status === 'succeeded';
  const completionUrls = completionSucceeded ? completionJob?.output_urls ?? [] : [];
  const completionAssetIds = completionSucceeded ? completionJob?.output_asset_ids ?? [] : [];
  const completionViews = completionSucceeded ? completionJob?.character_views ?? [] : [];
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
      ? job.linked_character_id ?? job.linked_scene_id ?? fallbackLinkRefId ?? null
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
  const showCompleteCharacterViews = Boolean(canCompleteCharacterViews && onCompleteCharacterViews);

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

  const openSaveCoverSkill = () => {
    setCoverSkillTitle('');
    setCoverSkillDescription('');
    setCoverSkillCredits(0);
    setSavingCoverSkillOpen(true);
  };

  const saveCoverSkill = async () => {
    if (!job.output_asset_id) return;
    const title = coverSkillTitle.trim();
    if (!title) return;
    setCoverSkillBusy(true);
    try {
      await api.post<CreationSkillDetail>('/v1/skills', {
        title,
        description: coverSkillDescription.trim(),
        category: 'cover_asset',
        cover_asset_id: job.output_asset_id,
        params: { cover_asset_id: job.output_asset_id },
        access_credits: coverSkillCredits,
      });
      notify(t('saveCoverSkillDone'), 'success');
      setSavingCoverSkillOpen(false);
    } catch {
      notify(t('saveCoverSkillFailed'), 'error');
    } finally {
      setCoverSkillBusy(false);
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
      ) : (
        <div className="relative aspect-video overflow-hidden rounded-[var(--radius-md)] border border-border bg-surface-soft">
          <div className="absolute inset-0 grid place-items-center px-6">
            <div className="flex flex-col items-center gap-2 text-center">
              <IconSparkle className={cn('size-5 text-amber', !finished && 'animate-pulse')} />
              <p aria-live="polite" className="tabular text-4xl font-semibold tracking-tight text-text">
                {job.progress}%
              </p>
              <p className="text-sm text-text">{t(stageLabelKey(displayStage, job.operation))}</p>
              {latestEvent?.message ? (
                <p className="max-w-md text-sm text-muted">{latestEvent.message}</p>
              ) : null}
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
        suspend at `awaiting_input` — mirrors `job-progress.tsx`'s own
        rendering (the only other place `AwaitingInputPanel` is used), so a
        job suspended here isn't stuck with no way to see or answer its
        follow-up question just because image creation never navigates to
        `/jobs/[jobId]`. */}
      {job.status === 'awaiting_input' && !job.cancel_requested ? (
        <AwaitingInputPanel key={job.id} jobId={job.id} />
      ) : null}
      {completionJob?.status === 'awaiting_input' && !completionJob.cancel_requested ? (
        <AwaitingInputPanel key={completionJob.id} jobId={completionJob.id} />
      ) : null}

      <div className="flex flex-wrap items-center gap-2">
        {finished && returnHref ? (
          <Button variant="primary" size="sm" onClick={() => router.push(returnHref)}>
            {tStudio('returnToScript')}
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
        {showCompleteCharacterViews ? (
          <Button
            variant="secondary"
            size="sm"
            loading={completingCharacterViews}
            onClick={onCompleteCharacterViews}
          >
            {completingCharacterViews
              ? tCharacters('completingViews')
              : tCharacters('completeViews')}
          </Button>
        ) : null}
        {job.status === 'succeeded' && draftId ? (
          <Button
            variant="secondary"
            size="sm"
            onClick={() => router.push(`/publish/${draftId}`)}
          >
            {tJob('publish')}
          </Button>
        ) : null}
        {canSaveCoverSkill ? (
          <Button variant="secondary" size="sm" onClick={openSaveCoverSkill}>
            {t('saveCoverSkill')}
          </Button>
        ) : null}
        {job.status === 'failed' || job.status === 'cancelled' ? (
          <Button variant="secondary" size="sm" loading={retrying} onClick={() => void retry()}>
            {tJob('retry')}
          </Button>
        ) : null}
      </div>

      <Dialog
        open={savingCoverSkillOpen}
        onClose={() => {
          if (!coverSkillBusy) setSavingCoverSkillOpen(false);
        }}
        title={t('saveCoverSkillTitle')}
        size="sm"
        footer={
          <>
            <Button
              variant="ghost"
              onClick={() => setSavingCoverSkillOpen(false)}
              disabled={coverSkillBusy}
            >
              {tActions('cancel')}
            </Button>
            <Button
              loading={coverSkillBusy}
              disabled={coverSkillTitle.trim().length === 0}
              onClick={() => void saveCoverSkill()}
            >
              {tActions('save')}
            </Button>
          </>
        }
      >
        <div className="flex flex-col gap-4">
          <p className="text-xs text-muted">{t('saveCoverSkillHint')}</p>
          <TextInput
            label={t('saveCoverSkillTitleLabel')}
            required
            maxLength={80}
            value={coverSkillTitle}
            onChange={(event) => setCoverSkillTitle(event.target.value)}
          />
          <TextArea
            label={t('saveCoverSkillDescriptionLabel')}
            maxLength={300}
            value={coverSkillDescription}
            onChange={(event) => setCoverSkillDescription(event.target.value)}
          />
          <AccessPriceField
            value={coverSkillCredits}
            onChange={setCoverSkillCredits}
            label={tSkills('priceLabel')}
            hint={tSkills('priceHint')}
          />
        </div>
      </Dialog>
    </div>
  );
}

function statusColor(status: string): string {
  if (status === 'succeeded') return 'text-success';
  if (status === 'failed') return 'text-danger';
  if (status === 'cancelled' || status === 'expired') return 'text-amber';
  return 'text-text';
}