'use client';

import { useTranslations } from 'next-intl';
import { useState } from 'react';

import { LineageGraph } from '@/components/lineage/lineage-graph';
import { VersionDiffPanel } from '@/components/lineage/version-diff-panel';
import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { ErrorNotice, Skeleton } from '@/components/ui/primitives';
import { useRouter } from '@/i18n/navigation';
import type { LineageResponse } from '@/lib/api/types';
import { useResource } from '@/lib/use-resource';

interface Selection {
  workVersionId: string;
  workId: string;
  title: string;
}

export function LineageDialog({
  workId,
  open,
  onClose,
}: {
  workId: string;
  open: boolean;
  onClose: () => void;
}) {
  const t = useTranslations('lineagePanel');
  const tActions = useTranslations('actions');
  const router = useRouter();

  const [selected, setSelected] = useState<Selection | null>(null);

  // Loaded on open rather than with the page: most visitors never expand the
  // graph, and the descendant tree is the largest payload on the work page.
  const lineage = useResource<LineageResponse>(open ? `/v1/works/${workId}/lineage` : null);

  return (
    <Dialog open={open} onClose={onClose} title={t('title')} size="lg">
      {lineage.status === 'failed' ? (
        <ErrorNotice title={t('failed')} />
      ) : !lineage.data ? (
        <div className="flex flex-col gap-3" aria-busy="true">
          <Skeleton className="h-56 w-full" />
          <Skeleton className="h-4 w-40" />
        </div>
      ) : (
        <div className="flex flex-col gap-5">
          <LineageGraph
            lineage={lineage.data}
            selectedVersionId={selected?.workVersionId}
            onSelect={setSelected}
          />

          {selected ? (
            <div className="flex flex-col gap-3">
              <div className="flex items-center justify-between gap-3">
                <p className="text-sm font-medium">{selected.title}</p>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => {
                    onClose();
                    router.push(`/work/${selected.workId}`);
                  }}
                >
                  {t('openWork')}
                </Button>
              </div>
              <VersionDiffPanel childVersionId={selected.workVersionId} />
            </div>
          ) : null}

          <div className="flex justify-end">
            <Button variant="ghost" onClick={onClose}>
              {tActions('close')}
            </Button>
          </div>
        </div>
      )}
    </Dialog>
  );
}
