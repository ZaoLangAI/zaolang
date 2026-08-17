'use client';

import Image from 'next/image';
import { useLocale, useTranslations } from 'next-intl';
import { useMemo } from 'react';

import { IconAlert, IconCheck } from '@/components/ui/icons';
import { Spinner } from '@/components/ui/spinner';
import type { Locale } from '@/i18n/routing';
import type { GenerationJob, Page } from '@/lib/api/types';
import { cn } from '@/lib/cn';
import { formatRelative } from '@/lib/format';
import { useResource } from '@/lib/use-resource';

/**
 * The image studio's version history — every generation job filed under the
 * same `Draft`, in the order they were made. Flat and chronological, not a
 * tree: branching from an older version just means picking it back up as the
 * next iteration's reference (`InlineImageResult`'s "基于此图继续微调"), so
 * there is nothing to render as a graph — the lineage graph
 * (`zaolang-lineage-graph`) is a different, published-`Work` concept.
 *
 * Fetches the draft's job list once per `draftId` (`useResource` refetches
 * only when the path changes) and merges in `activeJob` locally by id, so
 * the item for a job that is still generating stays live without a second
 * poller — `activeJob` is already streamed by the caller.
 */
export function GenerationVersionHistory({
  draftId,
  activeJob,
  onSelect,
}: {
  draftId: string | null;
  activeJob: GenerationJob | null;
  onSelect: (job: GenerationJob) => void;
}) {
  const t = useTranslations('remixPage');
  const tJob = useTranslations('job');
  const locale = useLocale() as Locale;

  const history = useResource<Page<GenerationJob>>(
    draftId ? `/v1/generation-jobs?draft_id=${draftId}` : null,
  );

  const versions = useMemo(() => {
    const byId = new Map<string, GenerationJob>();
    for (const job of history.data?.items ?? []) byId.set(job.id, job);
    if (activeJob) byId.set(activeJob.id, activeJob);
    return [...byId.values()].sort(
      (left, right) => new Date(left.created_at).getTime() - new Date(right.created_at).getTime(),
    );
  }, [history.data, activeJob]);

  if (!draftId || versions.length === 0) return null;

  return (
    <section aria-labelledby="generation-history-heading" className="flex flex-col gap-2">
      <h2 id="generation-history-heading" className="text-sm font-semibold">
        {t('generationHistory', { count: versions.length })}
      </h2>
      <ol className="flex gap-3 overflow-x-auto pb-1">
        {versions.map((job, index) => {
          const selected = job.id === activeJob?.id;
          const thumbnail = job.output_url ?? null;
          return (
            <li key={job.id} className="w-24 shrink-0">
              <button
                type="button"
                onClick={() => onSelect(job)}
                aria-current={selected ? 'true' : undefined}
                title={job.prompt ?? undefined}
                className={cn(
                  'block w-full overflow-hidden rounded-[var(--radius-sm)] border text-left transition-colors',
                  'focus-visible:outline-2',
                  selected
                    ? 'border-primary ring-1 ring-primary'
                    : 'border-border hover:border-border-strong',
                )}
              >
                <div className="relative aspect-square bg-surface-soft">
                  {thumbnail ? (
                    <Image src={thumbnail} alt="" fill sizes="96px" className="object-cover" />
                  ) : (
                    <div className="absolute inset-0 grid place-items-center">
                      <VersionStatusIcon status={job.status} />
                    </div>
                  )}
                  <span
                    className={cn(
                      'absolute left-1 top-1 rounded-full px-1.5 py-0.5 text-[10px] font-medium',
                      'bg-surface-raised/90 text-muted',
                    )}
                  >
                    V{index + 1}
                  </span>
                </div>
                <p className="truncate bg-surface px-1.5 py-1 text-[10px] text-muted">
                  {job.status === 'succeeded'
                    ? formatRelative(job.created_at, locale)
                    : tJob(job.status)}
                </p>
              </button>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

function VersionStatusIcon({ status }: { status: string }) {
  if (status === 'failed' || status === 'cancelled' || status === 'expired') {
    return <IconAlert className="size-4 text-danger" />;
  }
  if (status === 'succeeded') return <IconCheck className="size-4 text-success" />;
  return <Spinner className="size-4 text-muted" />;
}
