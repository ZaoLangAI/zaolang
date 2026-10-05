'use client';

import { Handle, Position, type NodeProps } from '@xyflow/react';
import { useTranslations } from 'next-intl';

import { IconChevronDown } from '@/components/ui/icons';
import { Badge } from '@/components/ui/primitives';
import { Spinner } from '@/components/ui/spinner';
import { cn } from '@/lib/cn';

import {
  LOOK_FOOTER,
  LOOK_HEADER,
  LOOK_ROW,
  LOOK_ROWS_PAD,
  LOOK_STRIP,
  MAX_LOOK_ROWS,
  STRIP_THUMBS,
  isApprovedEntry,
  type LookNode,
} from '../graph-model';
import { useAttributeLabel } from '../use-attribute-label';

/**
 * A look / scene variant as a class box: name, then its attribute rows,
 * then (collapsed) a strip of its approved images or (expanded) room for
 * its image nodes, which React Flow draws inside it. Sized exactly to
 * `lookSize` — the layout depends on it.
 */
export function LookNodeCard({ data, selected }: NodeProps<LookNode>) {
  const t = useTranslations('assetGraph');
  const label = useAttributeLabel();
  const { variant, rows, expanded } = data;
  const entries = variant.entries ?? [];
  const approved = entries.filter(isApprovedEntry);
  const candidates = entries.length - approved.length;
  const shownRows = rows.slice(0, MAX_LOOK_ROWS);
  const thumbs = approved.slice(0, STRIP_THUMBS);

  return (
    <div
      style={{ width: data.width, height: data.height }}
      className={cn(
        // Colours and the shadow only — React Flow rewrites `transform` on
        // every pan frame; animating it makes the node lag the pointer.
        'flex flex-col overflow-hidden rounded-[var(--radius-md)] border bg-surface shadow-sm transition-[border-color,box-shadow]',
        selected ? 'border-primary ring-2 ring-primary/40' : 'border-border',
        expanded && 'bg-surface-soft/60',
      )}
    >
      <Handle
        type="target"
        position={Position.Left}
        className="!size-3 !border-border !bg-surface"
      />
      <div
        style={{ height: LOOK_HEADER }}
        className="flex items-center gap-2 border-b border-border px-3"
      >
        <div className="min-w-0 flex-1">
          <p
            className="flex items-center gap-1.5 truncate text-sm font-semibold text-text"
            title={variant.name}
          >
            <span className="truncate">{variant.name}</span>
            {variant.is_default ? <Badge tone="primary">{t('defaultBadge')}</Badge> : null}
          </p>
          <p className="flex items-center gap-1 text-[11px] text-muted">
            {t('imageCount', { count: approved.length })}
            {candidates ? ` · ${t('candidateCount', { count: candidates })}` : ''}
            {data.pendingCount ? (
              <span className="inline-flex items-center gap-1 text-primary">
                · <Spinner className="size-3" /> {t('pendingCount', { count: data.pendingCount })}
              </span>
            ) : null}
          </p>
        </div>
        <button
          type="button"
          // A plain button inside the node: clicking it must not also select
          // the node (React Flow would treat the click as a node click).
          onClick={(event) => {
            event.stopPropagation();
            data.onToggle(variant.id);
          }}
          aria-expanded={expanded}
          aria-label={expanded ? t('collapse') : t('expand')}
          className="nodrag grid size-7 shrink-0 place-items-center rounded-[var(--radius-sm)] text-muted hover:bg-surface-soft hover:text-text focus-visible:outline-2"
        >
          <IconChevronDown
            className={cn('size-4 transition-transform', expanded && 'rotate-180')}
          />
        </button>
      </div>
      {shownRows.length ? (
        <dl
          style={{ paddingTop: LOOK_ROWS_PAD / 2, paddingBottom: LOOK_ROWS_PAD / 2 }}
          className="border-b border-border px-3"
        >
          {shownRows.map((row, index) => {
            const text = label(row);
            return (
              <div
                key={`${row.key}-${index}`}
                style={{ height: LOOK_ROW }}
                className="flex items-center gap-2 text-[11px]"
              >
                <dt className="w-16 shrink-0 truncate text-muted">{text.label}</dt>
                <dd className="min-w-0 truncate text-text" title={text.value}>
                  {text.value}
                </dd>
              </div>
            );
          })}
          {rows.length > MAX_LOOK_ROWS ? (
            <p style={{ height: LOOK_ROW }} className="flex items-center text-[11px] text-muted">
              {t('moreRows', { count: rows.length - MAX_LOOK_ROWS })}
            </p>
          ) : null}
        </dl>
      ) : null}
      {expanded ? (
        <div className="flex-1">
          {entries.length === 0 && !data.pendingCount ? (
            <p className="px-3 py-3 text-[11px] text-muted">{t('emptyLook')}</p>
          ) : null}
        </div>
      ) : (
        <div style={{ height: LOOK_STRIP }} className="flex items-center gap-1.5 px-3">
          {thumbs.length ? (
            thumbs.map((entry) => (
              <div
                key={entry.id}
                className={cn(
                  'relative size-12 shrink-0 overflow-hidden rounded-[var(--radius-sm)] border bg-surface-soft',
                  entry.id === data.anchorEntryId ? 'border-primary' : 'border-border',
                )}
              >
                {entry.url ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={entry.url}
                    alt=""
                    draggable={false}
                    className="h-full w-full object-cover"
                  />
                ) : null}
              </div>
            ))
          ) : (
            <p className="text-[11px] text-muted">{t('emptyLook')}</p>
          )}
          {approved.length > thumbs.length ? (
            <span className="text-[11px] text-muted">+{approved.length - thumbs.length}</span>
          ) : null}
        </div>
      )}
      <div
        style={{ height: LOOK_FOOTER }}
        className="flex items-center justify-between border-t border-border px-3 text-[11px] text-muted"
      >
        <span className="truncate">{expanded ? t('expandedHint') : t('collapsedHint')}</span>
        {data.voiceName ? (
          <span
            className="ml-2 shrink-0 truncate rounded-full border border-border px-1.5 text-text"
            title={data.voiceName}
          >
            ♪ {data.voiceName}
          </span>
        ) : null}
      </div>
      <Handle
        type="source"
        position={Position.Right}
        className="!size-3 !border-border !bg-surface"
      />
    </div>
  );
}
