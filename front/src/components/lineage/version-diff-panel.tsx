'use client';

import { useTranslations } from 'next-intl';

import { Skeleton } from '@/components/ui/primitives';
import type { VersionDiff, VersionDiffEntry } from '@/lib/api/types';
import { cn } from '@/lib/cn';
import { useResource } from '@/lib/use-resource';

type DiffKind = 'added' | 'removed' | 'modified';

const KIND_STYLES: Record<DiffKind, string> = {
  added: 'bg-success/10 text-success',
  removed: 'bg-danger/10 text-danger',
  modified: 'bg-amber/10 text-amber',
};

/**
 * What one generation changed relative to its parent.
 *
 * Only changed fields are shown; an unchanged prompt in a list of ten rows
 * buries the one value the reader is looking for. A field missing on one
 * side reads very differently from one whose value merely changed, so each
 * row is classified into one of three states rather than sharing a look.
 */
export function VersionDiffPanel({ childVersionId }: { childVersionId: string }) {
  const t = useTranslations('lineagePanel');

  const diff = useResource<VersionDiff>(`/v1/work-versions/${childVersionId}/diff`);

  if (diff.status === 'loading') return <Skeleton className="h-24 w-full" />;

  // A root version legitimately has no parent, so a failed lookup is an empty
  // state rather than an error worth showing.
  const changed = (diff.data?.entries ?? []).filter((entry) => entry.changed);
  if (changed.length === 0) {
    return <p className="text-xs text-muted">{t('diffEmpty')}</p>;
  }

  const kindLabel: Record<DiffKind, string> = {
    added: t('diffAdded'),
    removed: t('diffRemoved'),
    modified: t('diffModified'),
  };

  return (
    <section>
      <h3 className="mb-2 text-xs font-semibold text-muted">{t('diffTitle')}</h3>
      <div className="overflow-hidden rounded-[var(--radius-sm)] border border-border">
        <table className="w-full text-left text-xs">
          <thead className="bg-surface-soft text-muted">
            <tr>
              <th scope="col" className="w-28 px-3 py-2 font-medium">
                {t('diffField')}
              </th>
              <th scope="col" className="px-3 py-2 font-medium">
                {t('diffBefore')}
              </th>
              <th scope="col" className="px-3 py-2 font-medium">
                {t('diffAfter')}
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {changed.map((entry) => {
              const kind = classify(entry);
              return (
                <tr key={entry.field}>
                  <th scope="row" className="px-3 py-2 text-left font-medium">
                    <span className="flex flex-col gap-1">
                      <span
                        className={cn(
                          'w-fit rounded-full px-1.5 py-0.5 text-[10px] font-medium',
                          KIND_STYLES[kind],
                        )}
                      >
                        {kindLabel[kind]}
                      </span>
                      <span>{entry.field}</span>
                    </span>
                  </th>
                  <td
                    className={cn(
                      'px-3 py-2 align-top text-muted',
                      kind !== 'added' && 'line-through decoration-danger/60',
                    )}
                  >
                    {render(entry.parent_value)}
                  </td>
                  <td className="px-3 py-2 align-top text-text">{render(entry.child_value)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

/**
 * A field present on only one side of the edge is an addition or a removal;
 * present on both with a different value is a modification. `parent_value`/
 * `child_value` collapse "missing" and "explicitly null" to the same `null`,
 * so this is a best-effort read of the pair — accurate for the plain
 * string/number/boolean params `reusable_params_json` actually carries.
 */
function classify(entry: VersionDiffEntry): DiffKind {
  const hasParent = !isEmpty(entry.parent_value);
  const hasChild = !isEmpty(entry.child_value);
  if (!hasParent && hasChild) return 'added';
  if (hasParent && !hasChild) return 'removed';
  return 'modified';
}

function isEmpty(value: unknown): boolean {
  return value === null || value === undefined || value === '';
}

function render(value: unknown): string {
  if (isEmpty(value)) return '—';
  if (typeof value === 'string') return value;
  return JSON.stringify(value);
}
