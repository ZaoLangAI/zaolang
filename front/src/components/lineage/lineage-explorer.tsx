'use client';

import { useTranslations } from 'next-intl';
import { useState } from 'react';

import { LineageGraph } from '@/components/lineage/lineage-graph';
import { VersionDiffPanel } from '@/components/lineage/version-diff-panel';
import { Button } from '@/components/ui/button';
import { ErrorNotice, Skeleton } from '@/components/ui/primitives';
import type { LineageResponse } from '@/lib/api/types';
import { useResource } from '@/lib/use-resource';

interface Selection {
  workVersionId: string;
  workId: string;
  title: string;
}

/**
 * Graph on top, parameter diff below — shared between the standalone lineage
 * dialog and any surface that wants the same explorer without a dialog shell
 * of its own (the discover preview embeds it directly).
 *
 * Always stacked rather than side-by-side: the diff only appears once a node
 * is picked, and putting it underneath keeps that cause-and-effect readable
 * at every viewport instead of only on narrow ones.
 */
export function LineageExplorer({
  workId,
  onOpenWork,
}: {
  workId: string;
  /** Lets the caller close its own dialog before navigating to the work. */
  onOpenWork: (workId: string) => void;
}) {
  const t = useTranslations('lineagePanel');
  const [selected, setSelected] = useState<Selection | null>(null);

  // Loaded on demand rather than with the page: most visitors never expand
  // the graph, and the descendant tree is the largest payload around a work.
  const lineage = useResource<LineageResponse>(`/v1/works/${workId}/lineage`);

  if (lineage.status === 'failed') return <ErrorNotice title={t('failed')} />;

  if (!lineage.data) {
    return (
      <div className="flex flex-col gap-3" aria-busy="true">
        <Skeleton className="h-56 w-full" />
        <Skeleton className="h-4 w-40" />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <LineageGraph
        lineage={lineage.data}
        selectedVersionId={selected?.workVersionId}
        onSelect={setSelected}
      />

      <div className="rounded-[var(--radius-md)] border border-border bg-surface p-4">
        {selected ? (
          <div className="flex flex-col gap-3">
            <div className="flex items-center justify-between gap-3">
              <p className="text-sm font-medium">{selected.title}</p>
              <Button variant="secondary" size="sm" onClick={() => onOpenWork(selected.workId)}>
                {t('openWork')}
              </Button>
            </div>
            <VersionDiffPanel childVersionId={selected.workVersionId} />
          </div>
        ) : (
          <p className="text-xs leading-relaxed text-muted">{t('selectHint')}</p>
        )}
      </div>
    </div>
  );
}
