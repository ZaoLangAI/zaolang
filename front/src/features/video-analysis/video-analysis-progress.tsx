'use client';

import { useTranslations } from 'next-intl';
import { useState } from 'react';

import { cancelVideoAnalysis } from '@/features/video-analysis/api';
import { Button } from '@/components/ui/button';
import { ErrorNotice } from '@/components/ui/primitives';
import { Spinner } from '@/components/ui/spinner';
import type { GenerationJob } from '@/lib/api/types';

const TERMINAL = new Set(['succeeded', 'failed', 'cancelled', 'expired']);

/**
 * The queued/running strip shown while a `video_analysis` job is in flight,
 * and the failure notice once it lands on a non-`succeeded` terminal status.
 * The `succeeded` case is not handled here — the caller switches to
 * `VideoAnalysisResult` for that, the same "one component owns the
 * structured result" split the rest of this feature keeps.
 */
export function VideoAnalysisProgress({
  job,
  onCancelled,
}: {
  job: GenerationJob;
  onCancelled: (job: GenerationJob) => void;
}) {
  const t = useTranslations('videoAnalysisPage');
  const tJob = useTranslations('job');
  const [cancelling, setCancelling] = useState(false);

  if (job.status === 'succeeded') return null;

  if (TERMINAL.has(job.status)) {
    return (
      <ErrorNotice
        title={job.failure_message || tJob(job.status)}
        detail={job.failure_code ? tJob('errorCode', { code: job.failure_code }) : undefined}
      />
    );
  }

  const cancel = async () => {
    setCancelling(true);
    try {
      onCancelled(await cancelVideoAnalysis(job.id));
    } catch {
      // Best-effort — the job stream will still catch up to a cancellation
      // that lands server-side even if this particular request failed.
    } finally {
      setCancelling(false);
    }
  };

  return (
    <div className="flex flex-col gap-3 rounded-[var(--radius-md)] border border-border bg-surface-soft p-4">
      <div className="flex items-center justify-between gap-3">
        <p className="flex items-center gap-2 text-sm">
          <Spinner />
          {tJob(job.status)}
        </p>
        <span className="tabular text-xs text-muted">
          {tJob('progress', { percent: job.progress })}
        </span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-track">
        <div
          className="h-full rounded-full bg-primary transition-[width]"
          style={{ width: `${Math.min(100, Math.max(0, job.progress))}%` }}
        />
      </div>
      {!job.cancel_requested ? (
        <Button
          variant="secondary"
          size="sm"
          className="self-start"
          loading={cancelling}
          onClick={() => void cancel()}
        >
          {t('cancel')}
        </Button>
      ) : (
        <p className="text-xs text-muted">{tJob('cancelRequested')}</p>
      )}
    </div>
  );
}
