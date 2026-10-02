'use client';

import { useLocale, useTranslations } from 'next-intl';
import { useState } from 'react';

import { QualityTierField } from '@/components/studio/quality-tier-field';
import { RightsAndEstimate } from '@/components/studio/rights-and-estimate';
import { Button } from '@/components/ui/button';
import { TextArea } from '@/components/ui/field';
import { IconRefresh } from '@/components/ui/icons';
import { useVideoAnalysisSubmit } from '@/features/video-analysis/use-video-analysis-submit';
import { VideoAnalysisHistory } from '@/features/video-analysis/video-analysis-history';
import { VideoAnalysisProgress } from '@/features/video-analysis/video-analysis-progress';
import { VideoAnalysisResult } from '@/features/video-analysis/video-analysis-result';
import { VideoUploadField } from '@/features/video-analysis/video-upload-field';
import type { Locale } from '@/i18n/routing';
import type { GenerationJob, QualityTier } from '@/lib/api/types';
import { formatCount, formatDuration } from '@/lib/format';
import { useJobStream } from '@/lib/use-job-stream';
import type { Asset } from '@/lib/upload';

const NOTES_MAX_LENGTH = 2000;
const TERMINAL = new Set(['succeeded', 'failed', 'cancelled', 'expired']);

/**
 * The "视频解析" tool's whole studio: submit form + inline progress/result
 * on one tab, the history list on the other — no `/jobs/[jobId]` navigation
 * (the `zaolang-frontend-ui` skill's "creation never navigates to
 * `/jobs/[jobId]`" rule, extended by this feature to cover a text-output job
 * the same way image creation already covers a media one), because a jump away would lose the "补充说明" textarea state
 * on a submit the user wants to immediately iterate on.
 */
export function VideoAnalysisStudio() {
  const t = useTranslations('videoAnalysisPage');
  const tCredits = useTranslations('credits');
  const locale = useLocale() as Locale;

  const [tab, setTab] = useState<'submit' | 'history'>('submit');
  const [asset, setAsset] = useState<Asset | null>(null);
  const [notes, setNotes] = useState('');
  const [qualityTier, setQualityTier] = useState<QualityTier>('standard');
  const [rightsConfirmed, setRightsConfirmed] = useState(false);
  const [activeJob, setActiveJob] = useState<GenerationJob | null>(null);
  const [historyKey, setHistoryKey] = useState(0);

  const { job: streamedJob, applyJob } = useJobStream(activeJob?.id ?? '', activeJob);
  const job = streamedJob ?? activeJob;

  const { quote, quoteFailed, submitting, error, submit } = useVideoAnalysisSubmit(
    qualityTier,
    (submittedJob) => {
      setActiveJob(submittedJob);
      // The new job hasn't settled yet, but re-fetching once it does is the
      // history tab's own concern (it just needs a cache-buster once we know
      // a fresh one exists) — bumping here on every terminal transition
      // below covers that without this component polling on its own.
      setHistoryKey((key) => key + 1);
    },
  );

  const startOver = () => {
    setActiveJob(null);
    setAsset(null);
    setNotes('');
    setRightsConfirmed(false);
  };

  const handleCancelled = (cancelled: GenerationJob) => {
    applyJob(cancelled);
    setHistoryKey((key) => key + 1);
  };

  const estimate = quote ? formatDuration(quote.estimated_seconds) : '—';
  const price = quote ? tCredits('amount', { count: formatCount(quote.credits, locale) }) : '—';
  const canSubmit = Boolean(asset) && rightsConfirmed && !submitting;

  return (
    <div className="flex flex-col gap-6">
      <div role="tablist" aria-label={t('title')} className="flex gap-2 border-b border-border">
        {(['submit', 'history'] as const).map((id) => (
          <button
            key={id}
            role="tab"
            type="button"
            aria-selected={tab === id}
            onClick={() => setTab(id)}
            className={
              tab === id
                ? 'border-b-2 border-primary px-1 pb-3 text-sm font-medium text-primary'
                : 'border-b-2 border-transparent px-1 pb-3 text-sm text-muted hover:text-text'
            }
          >
            {id === 'submit' ? t('tabSubmit') : t('tabHistory')}
          </button>
        ))}
      </div>

      {tab === 'submit' ? (
        job ? (
          <div className="mx-auto flex w-full max-w-2xl flex-col gap-5">
            <VideoAnalysisProgress job={job} onCancelled={handleCancelled} />
            {job.status === 'succeeded' ? (
              <VideoAnalysisResult job={job} videoUrl={asset?.url} />
            ) : null}
            {TERMINAL.has(job.status) ? (
              <Button
                variant="secondary"
                className="self-start"
                onClick={startOver}
                icon={<IconRefresh className="size-4" />}
              >
                {t('tabSubmit')}
              </Button>
            ) : null}
          </div>
        ) : (
          <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">
            <div className="flex flex-col gap-5">
              <VideoUploadField asset={asset} onChange={setAsset} />
              <TextArea
                label={t('notesLabel')}
                placeholder={t('notesPlaceholder')}
                value={notes}
                maxLength={NOTES_MAX_LENGTH}
                onChange={(event) => setNotes(event.target.value)}
              />
            </div>

            <div className="flex flex-col gap-4">
              <QualityTierField tier={qualityTier} onChange={setQualityTier} quote={quote} />
              <RightsAndEstimate
                rightsConfirmed={rightsConfirmed}
                onRightsChange={setRightsConfirmed}
                quote={quote}
                quoteFailed={quoteFailed}
                estimate={estimate}
                price={price}
                error={error}
              />
              {!asset ? <p className="text-xs text-muted">{t('missingVideo')}</p> : null}
              <Button
                fullWidth
                loading={submitting}
                disabled={!canSubmit}
                onClick={() => {
                  if (asset) submit({ referenceAssetId: asset.id, notes });
                }}
              >
                {submitting ? t('submitting') : t('submit')}
              </Button>
            </div>
          </div>
        )
      ) : (
        <VideoAnalysisHistory refreshKey={historyKey} />
      )}
    </div>
  );
}
