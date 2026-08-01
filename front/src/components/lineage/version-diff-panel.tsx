'use client';

import { useTranslations } from 'next-intl';

import { Skeleton } from '@/components/ui/primitives';
import type { VersionDiff } from '@/lib/api/types';
import { useResource } from '@/lib/use-resource';

/**
 * What one generation changed relative to its parent.
 *
 * Only changed fields are shown; an unchanged prompt in a list of ten rows
 * buries the one value the reader is looking for.
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
            {changed.map((entry) => (
              <tr key={entry.field}>
                <th scope="row" className="px-3 py-2 text-left font-medium text-amber">
                  {entry.field}
                </th>
                <td className="px-3 py-2 align-top text-muted line-through decoration-danger/60">
                  {render(entry.parent_value)}
                </td>
                <td className="px-3 py-2 align-top text-text">{render(entry.child_value)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function render(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—';
  if (typeof value === 'string') return value;
  return JSON.stringify(value);
}
