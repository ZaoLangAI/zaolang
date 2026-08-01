'use client';

import { useTranslations } from 'next-intl';

import { cn } from '@/lib/cn';

type Json = unknown;

interface DiffRow {
  path: string;
  before?: Json;
  after?: Json;
  kind: 'added' | 'removed' | 'changed';
}

/**
 * Field-level diff between two configuration versions.
 *
 * Flattened to dotted paths rather than shown as two pretty-printed blobs: an
 * operator about to roll back needs to see *which* key changed, and a
 * side-by-side of 200 lines of JSON does not answer that.
 */
export function JsonDiff({ before, after }: { before: Json; after: Json }) {
  const t = useTranslations('admin');
  const rows = diff(before, after);

  if (rows.length === 0) {
    return <p className="text-xs text-muted">{t('diffNoChange')}</p>;
  }

  return (
    <div className="overflow-x-auto rounded-[var(--radius-sm)] border border-border">
      <table className="w-full text-left text-xs">
        <thead className="bg-surface-soft text-muted">
          <tr>
            <th scope="col" className="px-3 py-2 font-medium">
              path
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
          {rows.map((row) => (
            <tr key={row.path}>
              <th scope="row" className="px-3 py-2 text-left font-medium text-amber">
                {row.path}
              </th>
              <td
                className={cn(
                  'px-3 py-2 align-top font-mono',
                  row.kind === 'added'
                    ? 'text-muted'
                    : 'text-muted line-through decoration-danger/60',
                )}
              >
                {show(row.before)}
              </td>
              <td
                className={cn(
                  'px-3 py-2 align-top font-mono',
                  row.kind === 'removed' ? 'text-muted' : 'text-success',
                )}
              >
                {show(row.after)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function diff(before: Json, after: Json, prefix = ''): DiffRow[] {
  if (isRecord(before) && isRecord(after)) {
    const keys = [...new Set([...Object.keys(before), ...Object.keys(after)])].sort();
    return keys.flatMap((key) => diff(before[key], after[key], prefix ? `${prefix}.${key}` : key));
  }

  if (JSON.stringify(before) === JSON.stringify(after)) return [];

  const kind: DiffRow['kind'] =
    before === undefined ? 'added' : after === undefined ? 'removed' : 'changed';
  return [{ path: prefix || '(root)', before, after, kind }];
}

function show(value: Json): string {
  if (value === undefined) return '—';
  if (typeof value === 'string') return value;
  return JSON.stringify(value);
}
