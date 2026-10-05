'use client';

import type { NodeProps } from '@xyflow/react';
import { useTranslations } from 'next-intl';

import { Spinner } from '@/components/ui/spinner';

import { ENTRY_HEIGHT, ENTRY_WIDTH, type PendingNode } from '../graph-model';

/** A generation job still filling this look — becomes an image node (a
 * candidate) once it lands. */
export function PendingNodeCard({ data }: NodeProps<PendingNode>) {
  const t = useTranslations('assetGraph');
  return (
    <div
      role="status"
      style={{ width: ENTRY_WIDTH, height: ENTRY_HEIGHT }}
      className="flex flex-col items-center justify-center gap-2 rounded-[var(--radius-sm)] border border-dashed border-primary/60 bg-surface text-center"
    >
      <Spinner className="size-5" />
      <p className="px-1.5 text-[11px] text-muted">
        {data.job.status === 'queued' ? t('pendingQueued') : t('pendingRunning')}
      </p>
    </div>
  );
}
