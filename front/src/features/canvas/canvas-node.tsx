'use client';

import { Handle, NodeResizer, Position, type NodeProps } from '@xyflow/react';
import { useTranslations } from 'next-intl';

import { Badge } from '@/components/ui/primitives';
import { cn } from '@/lib/cn';

import type { CanvasNodeData } from './graph-convert';
import type { CanvasNodeKind } from './api';

/** Left border colour per node kind, so the shape of a story reads at a
 * glance when zoomed out past the point where labels are legible. */
const KIND_TONE: Record<CanvasNodeKind, string> = {
  series: 'border-l-text',
  episode: 'border-l-primary',
  shot: 'border-l-amber',
  skill: 'border-l-success',
  clip: 'border-l-primary',
  image: 'border-l-success',
  video: 'border-l-amber',
  prompt: 'border-l-muted',
  note: 'border-l-muted',
  agent: 'border-l-primary',
};

export function CanvasNodeCard({ data, selected }: NodeProps & { data: CanvasNodeData }) {
  const t = useTranslations('canvas');

  return (
    <>
      {/* Resizing is opt-in per selection so the handles do not clutter every
          card. Minimums keep a card from being shrunk past its own chrome. */}
      <NodeResizer
        isVisible={selected}
        minWidth={200}
        minHeight={72}
        lineClassName="!border-primary/60"
        handleClassName="!size-2 !rounded-sm !border-primary !bg-surface"
      />
      <div
        className={cn(
          // Only colours and the shadow animate. Bare `transition` would also
          // cover `transform`, which React Flow rewrites on every pan/zoom
          // frame to position the node — animating that makes dragging lag
          // behind the cursor and the node never settles.
          'h-full w-full min-w-60 max-w-80 rounded-[var(--radius-md)] border border-l-4 bg-surface shadow-sm transition-[color,background-color,border-color,box-shadow]',
          KIND_TONE[data.kind] ?? 'border-l-muted',
          selected ? 'border-primary ring-2 ring-primary/40' : 'border-border',
          // A stale node is dimmed but never hidden — losing the card would
          // lose the layout the user built around it.
          data.stale && 'opacity-60',
        )}
      >
        <Handle type="target" position={Position.Left} className="!bg-border" />

        {data.thumbnailUrl ? (
          <div className="aspect-video w-full overflow-hidden rounded-t-[var(--radius-md)] bg-surface-soft">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={data.thumbnailUrl}
              alt=""
              className="h-full w-full object-cover"
              draggable={false}
            />
          </div>
        ) : null}

        <div className="space-y-1 p-3">
          <div className="flex items-center justify-between gap-2">
            <Badge>{t(`kind.${data.kind}`)}</Badge>
            {data.stale ? <Badge tone="danger">{t('staleBadge')}</Badge> : null}
          </div>
          <p className="truncate text-sm font-medium text-text" title={data.label}>
            {data.label || t('untitledNode')}
          </p>
          {data.subtitle ? (
            <p className="truncate text-xs text-muted" title={data.subtitle}>
              {data.subtitle}
            </p>
          ) : null}
          {data.stale ? <p className="text-xs text-danger">{t('staleHint')}</p> : null}
        </div>

        <Handle type="source" position={Position.Right} className="!bg-border" />
      </div>
    </>
  );
}
