'use client';

import { useTranslations } from 'next-intl';

import { Spinner } from '@/components/ui/spinner';
import { cn } from '@/lib/cn';

export interface Column<T> {
  id: string;
  header: string;
  /** Right-aligned and tabular; use for anything the reader will compare. */
  numeric?: boolean;
  width?: string;
  render: (row: T) => React.ReactNode;
}

/**
 * The console's one table.
 *
 * Every operational list is the same shape — a header row, selectable rows, a
 * row action that opens a detail drawer — so they share one implementation and
 * one set of keyboard and empty-state behaviours.
 */
export function DataTable<T>({
  columns,
  rows,
  rowKey,
  loading = false,
  failed = false,
  onRowClick,
  activeKey,
  selectable = false,
  selected,
  onSelectedChange,
  caption,
  emptyLabel,
}: {
  columns: Array<Column<T>>;
  rows: T[];
  rowKey: (row: T) => string;
  loading?: boolean;
  failed?: boolean;
  onRowClick?: (row: T) => void;
  activeKey?: string;
  selectable?: boolean;
  selected?: Set<string>;
  onSelectedChange?: (next: Set<string>) => void;
  caption: string;
  /** For lists where empty is the healthy outcome, such as dangling reserves. */
  emptyLabel?: string;
}) {
  const t = useTranslations('admin');

  const allSelected =
    selectable && rows.length > 0 && rows.every((row) => selected?.has(rowKey(row)));

  const toggleAll = () => {
    if (!onSelectedChange) return;
    onSelectedChange(allSelected ? new Set() : new Set(rows.map(rowKey)));
  };

  const toggleOne = (key: string) => {
    if (!onSelectedChange) return;
    const next = new Set(selected);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    onSelectedChange(next);
  };

  return (
    <div className="overflow-x-auto rounded-[var(--radius-md)] border border-border">
      <table className="w-full text-left text-sm">
        <caption className="sr-only">{caption}</caption>
        <thead className="bg-surface-soft text-xs text-muted">
          <tr>
            {selectable ? (
              <th scope="col" className="w-10 px-3 py-2.5">
                <input
                  type="checkbox"
                  aria-label={caption}
                  checked={allSelected}
                  onChange={toggleAll}
                  className="size-4 accent-[var(--primary)]"
                />
              </th>
            ) : null}
            {columns.map((column) => (
              <th
                key={column.id}
                scope="col"
                style={column.width ? { width: column.width } : undefined}
                className={cn(
                  'whitespace-nowrap px-3 py-2.5 font-medium',
                  column.numeric && 'text-right',
                )}
              >
                {column.header}
              </th>
            ))}
          </tr>
        </thead>

        <tbody className="divide-y divide-border bg-surface">
          {loading ? (
            <tr>
              <td
                colSpan={columns.length + (selectable ? 1 : 0)}
                className="px-3 py-10 text-center"
              >
                <Spinner className="mx-auto size-5" />
              </td>
            </tr>
          ) : failed ? (
            <tr>
              <td
                colSpan={columns.length + (selectable ? 1 : 0)}
                className="px-3 py-10 text-center text-sm text-danger"
              >
                {t('loadFailed')}
              </td>
            </tr>
          ) : rows.length === 0 ? (
            <tr>
              <td
                colSpan={columns.length + (selectable ? 1 : 0)}
                className="px-3 py-10 text-center"
              >
                <p className="text-sm">{emptyLabel ?? t('empty')}</p>
                {emptyLabel ? null : <p className="mt-1 text-xs text-muted">{t('emptyHint')}</p>}
              </td>
            </tr>
          ) : (
            rows.map((row) => {
              const key = rowKey(row);
              return (
                <tr
                  key={key}
                  // A row is not a button, so activation goes through the cell
                  // content; the whole row is still clickable for the mouse.
                  onClick={onRowClick ? () => onRowClick(row) : undefined}
                  className={cn(
                    onRowClick && 'cursor-pointer',
                    activeKey === key ? 'bg-primary/8' : 'hover:bg-surface-soft',
                  )}
                >
                  {selectable ? (
                    <td className="px-3 py-2.5" onClick={(event) => event.stopPropagation()}>
                      <input
                        type="checkbox"
                        aria-label={key}
                        checked={selected?.has(key) ?? false}
                        onChange={() => toggleOne(key)}
                        className="size-4 accent-[var(--primary)]"
                      />
                    </td>
                  ) : null}
                  {columns.map((column, index) => {
                    const content = column.render(row);
                    const className = cn(
                      'px-3 py-2.5 align-top',
                      column.numeric && 'tabular whitespace-nowrap text-right',
                    );
                    // The first cell is the row header, which is what a screen
                    // reader announces when moving between columns.
                    return index === 0 && !selectable ? (
                      <th key={column.id} scope="row" className={cn(className, 'font-normal')}>
                        {onRowClick ? (
                          <button
                            type="button"
                            onClick={(event) => {
                              event.stopPropagation();
                              onRowClick(row);
                            }}
                            className="text-left text-primary hover:underline"
                          >
                            {content}
                          </button>
                        ) : (
                          content
                        )}
                      </th>
                    ) : (
                      <td key={column.id} className={className}>
                        {content}
                      </td>
                    );
                  })}
                </tr>
              );
            })
          )}
        </tbody>
      </table>
    </div>
  );
}
