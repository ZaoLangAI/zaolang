'use client';

import { useTranslations } from 'next-intl';
import { useState } from 'react';

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

  const characterViews = job.character_views ?? null;
  const hasMultipleOutputs = (job.output_urls?.length ?? 0) > 1;
  const outputLabels =
    characterViews && characterViews.length === job.output_urls?.length
      ? characterViews.map((view) => tCharacters(CHARACTER_VIEW_LABEL_KEY[view] ?? 'viewFront'))
      : undefined;

  const refreshOutputSrc = () =>
    job.output_asset_id ? refreshAssetUrl(job.output_asset_id) : refreshJobOutputUrl(job.id);

  const canUseAsReference = job.status === 'succeeded' && Boolean(job.output_asset_id);
  const canSaveCoverSkill =
    job.status === 'succeeded' && job.asset_kind === 'cover' && Boolean(job.output_asset_id);

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
      {hasMultipleOutputs && job.output_urls ? (
        <OutputGallery
          urls={job.output_urls}
          assetIds={job.output_asset_ids}
          mediaType={job.output_media_type ?? 'image'}
          title={t('title')}
          labels={outputLabels}
          itemLabel={(index, total) => t('outputItemLabel', { index, total })}
        />
      ) : job.output_url ? (
        <DevicePreview
          src={job.output_url}
          title={t('title')}
          mediaType="image"
          refreshSrc={refreshOutputSrc}
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

      <div className="flex flex-wrap items-center gap-2">
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
        {!finished ? (
          <Button
            variant="ghost"
            size="sm"
            onClick={onCancel}
            loading={cancelling}
            disabled={job.cancel_requested}
          >
            {job.cancel_requested ? tJob('cancelRequested') : tJob('cancel')}
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