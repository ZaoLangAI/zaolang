'use client';

import { useTranslations } from 'next-intl';

import type { CardKind } from '@/components/library/entry-actions';
import type { AssetGraph } from '@/lib/api/types';
import { cn } from '@/lib/cn';

import { attributeRows, isApprovedEntry, outlineOrder, type GraphSelection } from './graph-model';
import { useAttributeLabel } from './use-attribute-label';

/**
 * The graph as an indented list for narrow screens (no canvas below `md`):
 * looks in derivation order, indented by depth, each with its attribute
 * rows and image thumbnails. Same selection as the canvas — tapping opens
 * the inspector.
 */
export function AssetGraphOutline({
  graph,
  kind,
  selection,
  onSelect,
}: {
  graph: AssetGraph;
  kind: CardKind;
  selection: GraphSelection;
  onSelect: (selection: GraphSelection) => void;
}) {
  const t = useTranslations('assetGraph');
  const label = useAttributeLabel();
  const names = new Map((graph.variants ?? []).map((v) => [v.id, v.name]));
  return (
    <ol className="flex flex-col gap-2">
      {outlineOrder(graph).map(({ variant, depth, parents }) => {
        const selected = selection.type === 'variant' && selection.id === variant.id;
        const approved = (variant.entries ?? []).filter(isApprovedEntry);
        return (
          <li key={variant.id} style={{ marginInlineStart: Math.min(depth, 4) * 16 }}>
            <div
              className={cn(
                'rounded-[var(--radius-md)] border bg-surface p-3',
                selected ? 'border-primary ring-2 ring-primary/30' : 'border-border',
              )}
            >
              <button
                type="button"
                onClick={() => onSelect({ type: 'variant', id: variant.id })}
                className="flex w-full flex-col items-start gap-1 text-left focus-visible:outline-2"
              >
                <span className="text-sm font-semibold">{variant.name}</span>
                {parents.length ? (
                  <span className="text-[11px] text-muted">
                    {t('derivedFrom', {
                      names: parents.map((id) => names.get(id) ?? id).join('、'),
                    })}
                  </span>
                ) : null}
                <span className="flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-muted">
                  {attributeRows(variant, kind).map((row, index) => {
                    const text = label(row);
                    return (
                      <span key={index}>
                        {text.label}: <span className="text-text">{text.value}</span>
                      </span>
                    );
                  })}
                </span>
              </button>
              {(variant.entries ?? []).length ? (
                <ul className="mt-2 flex flex-wrap gap-1.5">
                  {(variant.entries ?? []).map((entry) => (
                    <li key={entry.id}>
                      <button
                        type="button"
                        aria-label={t('openImage')}
                        onClick={() => onSelect({ type: 'entry', id: entry.id })}
                        className={cn(
                          'size-14 overflow-hidden rounded-[var(--radius-sm)] border bg-surface-soft focus-visible:outline-2',
                          selection.type === 'entry' && selection.id === entry.id
                            ? 'border-primary'
                            : 'border-border',
                          !approved.includes(entry) && 'border-dashed opacity-70',
                        )}
                      >
                        {entry.url ? (
                          // eslint-disable-next-line @next/next/no-img-element
                          <img src={entry.url} alt="" className="h-full w-full object-cover" />
                        ) : null}
                      </button>
                    </li>
                  ))}
                </ul>
              ) : null}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
