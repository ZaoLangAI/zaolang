'use client';

import { useTranslations } from 'next-intl';

import { VideoPlayer } from '@/components/media/video-player';
import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { Badge } from '@/components/ui/primitives';
import { Spinner } from '@/components/ui/spinner';
import { cn } from '@/lib/cn';
import type { GenerationJob } from '@/lib/api/types';
import { useJobStream } from '@/lib/use-job-stream';

/**
 * Lets the author pick one of the 2-3 cheap `preview`-tier drafts to promote
 * to full generation. Each card polls its own job independently via
 * `useJobStream` — the same hook the full job page uses — rather than a new
 * polling primitive.
 */
export function PreviewPickerDialog({
  open,
  jobs,
  targetQualityTierLabel,
  promoting,
  promoteError,
  onPick,
  onClose,
}: {
  open: boolean;
  jobs: GenerationJob[];
  /** Already-translated label of the tier the pick will be promoted to
   * (e.g. "标准"/"电影级") — resolved by the caller, which already owns the
   * `remixPage` tier copy, rather than duplicating it here. */
  targetQualityTierLabel: string;
  promoting: boolean;
  promoteError: string | null;
  onPick: (job: GenerationJob) => void;
  onClose: () => void;
}) {
  const t = useTranslations('shortform');

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={t('previewDialogTitle')}
      description={t('previewDialogDescription', { tier: targetQualityTierLabel })}
      size="lg"
    >
      {promoteError ? (
        <p role="alert" className="mb-3 text-xs text-danger">
          {promoteError}
        </p>
      ) : null}
      <ul className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        {jobs.map((job, index) => (
          <li key={job.id}>
            <PreviewCard
              job={job}
              index={index}
              disabled={promoting}
              onPick={() => onPick(job)}
            />
          </li>
        ))}
      </ul>
    </Dialog>
  );
}

function PreviewCard({
  job: initial,
  index,
  disabled,
  onPick,
}: {
  job: GenerationJob;
  index: number;
  disabled: boolean;
  onPick: () => void;
}) {
  const t = useTranslations('shortform');
  const { job } = useJobStream(initial.id, initial);
  const current = job ?? initial;

  const succeeded = current.status === 'succeeded' && Boolean(current.output_url);
  const failed = current.status === 'failed' || current.status === 'cancelled' || current.status === 'expired';
  const running = !succeeded && !failed;

  return (
    <div
      className={cn(
        'flex flex-col overflow-hidden rounded-[var(--radius-md)] border',
        succeeded ? 'border-border' : 'border-border/60',
      )}
    >
      <div className="relative flex aspect-[9/16] items-center justify-center bg-surface-soft">
        {succeeded ? (
          <VideoPlayer src={current.output_url} title={t('previewCandidateLabel', { index: index + 1 })} bare />
        ) : (
          <div className="flex flex-col items-center gap-2 text-muted">
            {running ? <Spinner /> : null}
            <p className="text-xs">
              {failed ? t('previewStatusFailed') : t('previewStatusGenerating')}
            </p>
          </div>
        )}
        <Badge tone={succeeded ? 'success' : failed ? 'danger' : 'neutral'} className="absolute left-2 top-2">
          {t('previewCandidateLabel', { index: index + 1 })}
        </Badge>
      </div>
      <div className="p-2.5">
        <Button
          size="sm"
          fullWidth
          disabled={!succeeded || disabled}
          onClick={onPick}
        >
          {t('previewPick')}
        </Button>
      </div>
    </div>
  );
}
