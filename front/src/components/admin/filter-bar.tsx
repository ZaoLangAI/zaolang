'use client';

import { useTranslations } from 'next-intl';

import { Button } from '@/components/ui/button';
import { IconSearch } from '@/components/ui/icons';
import { cn } from '@/lib/cn';

export interface FilterDef {
  id: string;
  label: string;
  kind: 'text' | 'select';
  options?: Array<{ value: string; label: string }>;
  placeholder?: string;
}

/**
 * Column filters for a console list.
 *
 * State lives in the parent as a plain record so it can be lifted straight into
 * a query string: a filtered view has to be shareable with the colleague who
 * asked about it.
 */
export function FilterBar({
  filters,
  values,
  onChange,
  onReset,
  children,
}: {
  filters: FilterDef[];
  values: Record<string, string>;
  onChange: (id: string, value: string) => void;
  onReset: () => void;
  children?: React.ReactNode;
}) {
  const t = useTranslations('admin');
  const dirty = Object.values(values).some((value) => value !== '');

  return (
    <div className="flex flex-wrap items-end gap-3 rounded-[var(--radius-md)] border border-border bg-surface p-3">
      {filters.map((filter) => (
        <label key={filter.id} className="flex flex-col gap-1 text-xs text-muted">
          {filter.label}
          {filter.kind === 'select' ? (
            <select
              value={values[filter.id] ?? ''}
              onChange={(event) => onChange(filter.id, event.target.value)}
              className="h-9 rounded-[var(--radius-sm)] border border-border bg-surface-soft px-2.5 text-sm text-text"
            >
              <option value="">{t('filters')}</option>
              {filter.options?.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          ) : (
            <span className="relative">
              <IconSearch className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted" />
              <input
                type="search"
                value={values[filter.id] ?? ''}
                placeholder={filter.placeholder ?? t('search')}
                onChange={(event) => onChange(filter.id, event.target.value)}
                className={cn(
                  'h-9 w-48 rounded-[var(--radius-sm)] border border-border bg-surface-soft pl-8 pr-2.5 text-sm text-text',
                  'placeholder:text-muted/70',
                )}
              />
            </span>
          )}
        </label>
      ))}

      {dirty ? (
        <Button size="sm" variant="ghost" onClick={onReset}>
          {t('reset')}
        </Button>
      ) : null}

      <div className="ml-auto flex items-center gap-2">{children}</div>
    </div>
  );
}

/** Cursor pagination. Offsets drift when rows are being written underneath. */
export function Pager({
  onPrev,
  onNext,
  hasPrev,
  hasNext,
  summary,
}: {
  onPrev: () => void;
  onNext: () => void;
  hasPrev: boolean;
  hasNext: boolean;
  summary?: string;
}) {
  const t = useTranslations('admin');
  return (
    <nav className="flex items-center justify-between gap-3 py-3" aria-label={t('nextPage')}>
      <span className="text-xs text-muted">{summary}</span>
      <span className="flex gap-2">
        <Button size="sm" variant="secondary" disabled={!hasPrev} onClick={onPrev}>
          {t('prevPage')}
        </Button>
        <Button size="sm" variant="secondary" disabled={!hasNext} onClick={onNext}>
          {t('nextPage')}
        </Button>
      </span>
    </nav>
  );
}
