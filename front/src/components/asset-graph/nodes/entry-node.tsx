'use client';

import { Handle, Position, type NodeProps } from '@xyflow/react';
import { useTranslations } from 'next-intl';

import { Badge } from '@/components/ui/primitives';
import { Spinner } from '@/components/ui/spinner';
import { cn } from '@/lib/cn';

import { ENTRY_HEIGHT, ENTRY_WIDTH, type EntryNode } from '../graph-model';

/** One image inside an expanded look. Its own handles carry image-level
 * relations (调整修改 / 派生 from this exact image). */
export function EntryNodeCard({ data, selected }: NodeProps<EntryNode>) {
  const t = useTranslations('assetVariants');
  const tGraph = useTranslations('assetGraph');
  const { entry } = data;
  const candidate = entry.status === 'candidate';
  return (
    <div
      style={{ width: ENTRY_WIDTH, height: ENTRY_HEIGHT }}
      className={cn(
        'flex flex-col overflow-hidden rounded-[var(--radius-sm)] border bg-surface transition-[border-color,box-shadow]',
        selected
          ? 'border-primary ring-2 ring-primary/40'
          : candidate
            ? 'border-dashed border-border'
            : 'border-border',
      )}
    >
      <Handle
        type="target"
        position={Position.Left}
        className="!size-2.5 !border-border !bg-surface"
      />
      <div className={cn('relative h-24 w-full bg-surface-soft', candidate && 'opacity-70')}>
        {entry.url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={entry.url} alt="" draggable={false} className="h-full w-full object-cover" />
        ) : null}
        {data.isAnchor ? (
          <span className="absolute left-1 top-1">
            <Badge tone="primary">{t('anchor')}</Badge>
          </span>
        ) : candidate ? (
          <span className="absolute left-1 top-1">
            <Badge>{t('candidate')}</Badge>
          </span>
        ) : null}
        {data.versionCount > 1 || data.pendingVersions ? (
          <span className="absolute bottom-1 right-1 inline-flex items-center gap-1 rounded-full bg-surface/90 px-1.5 text-[10px] text-text">
            {data.pendingVersions ? <Spinner className="size-2.5" /> : null}
            {tGraph('versionBadge', { count: data.versionCount + data.pendingVersions })}
          </span>
        ) : null}
      </div>
      <p className="truncate px-1.5 py-1 text-[11px] text-muted">{t(`type.${entry.entry_type}`)}</p>
      <Handle
        type="source"
        position={Position.Right}
        className="!size-2.5 !border-border !bg-surface"
      />
    </div>
  );
}
