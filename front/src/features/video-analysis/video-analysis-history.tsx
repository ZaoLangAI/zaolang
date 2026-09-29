'use client';

import { useLocale, useTranslations } from 'next-intl';
import { useState } from 'react';

import { IconArrowLeft, IconSearch } from '@/components/ui/icons';
import { EmptyState, ErrorNotice } from '@/components/ui/primitives';
import { Spinner } from '@/components/ui/spinner';
import { VideoAnalysisResult } from '@/features/video-analysis/video-analysis-result';
import type { Locale } from '@/i18n/routing';
import type { GenerationJob, Page } from '@/lib/api/types';
import { cn } from '@/lib/cn';
import { formatDateTime } from '@/lib/format';
import { useResource } from '@/lib/use-resource';

const STATUS_TONE: Record<string, string> = {
  succeeded: 'text-success',
  failed: 'text-danger',
  cancelled: 'text-muted',
  expired: 'text-muted',
};

/**
 * The "历史记录" tab: every past `video_analysis` job for this user, newest
 * first, with the same `VideoAnalysisResult` detail view the just-submitted
 * flow uses — one rendering of the structured result, reused rather than a
 * second copy (see that component's own doc comment).
 *
 * `refreshKey` lets the studio force a re-fetch (e.g. right after a new
 * submission settles) without this component owning any submit logic
 * itself — `useResource` keys its cache off the path string, so folding the
 * key into the query string is enough to bust it.
 */
export function VideoAnalysisHistory({ refreshKey }: { refreshKey: number }) {
  const t = useTranslations('videoAnalysisPage');
  const tJob = useTranslations('job');
  const locale = useLocale() as Locale;
  const [selected, setSelected] = useState<GenerationJob | null>(null);

  const { status, data } = useResource<Page<GenerationJob>>(
    `/v1/generation-jobs?operation=video_analysis&limit=30&_r=${refreshKey}`,
  );

  if (selected) {
    return (
      <div className="flex flex-col gap-5">
        <button
          type="button"
          onClick={() => setSelected(null)}
          className="flex items-center gap-1.5 text-sm text-muted hover:text-text"
        >
          <IconArrowLeft className="size-4" />
          {t('backToHistory')}
        </button>
        {selected.status === 'succeeded' && selected.analysis ? (
          <VideoAnalysisResult job={selected} videoUrl={selected.reference_url} />
        ) : (
          <ErrorNotice
            title={tJob(selected.status)}
            detail={selected.failure_message ?? undefined}
          />
        )}
      </div>
    );
  }

  if (status === 'loading' || status === 'idle') {
    return (
      <div className="grid min-h-[30vh] place-items-center">
        <Spinner />
      </div>
    );
  }
  if (status === 'failed') {
    return <ErrorNotice title={t('historyLoadError')} />;
  }

  const items = data?.items ?? [];
  if (items.length === 0) {
    return (
      <EmptyState
        icon={<IconSearch className="size-6" />}
        title={t('historyEmpty')}
        description={t('historyEmptyHint')}
      />
    );
  }

  return (
    <ul className="flex flex-col gap-2">
      {items.map((job) => (
        <li key={job.id}>
          <button
            type="button"
            onClick={() => setSelected(job)}
            className="flex w-full items-center gap-3 rounded-[var(--radius-md)] border border-border bg-surface px-4 py-3 text-left transition-colors hover:border-border-strong hover:bg-surface-soft"
          >
            <div className="relative size-14 shrink-0 overflow-hidden rounded-[var(--radius-sm)] bg-surface-soft">
              {job.reference_url ? (
                <video
                  src={job.reference_url}
                  muted
                  preload="metadata"
                  className="size-full object-cover"
                />
              ) : null}
            </div>
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium">
                {job.prompt?.trim() || t('notesFallback')}
              </p>
              <p className="mt-0.5 text-xs text-muted">{formatDateTime(job.created_at, locale)}</p>
            </div>
            <span
              className={cn(
                'shrink-0 text-xs font-medium',
                STATUS_TONE[job.status] ?? 'text-muted',
              )}
            >
              {tJob(job.status)}
            </span>
          </button>
        </li>
      ))}
    </ul>
  );
}
