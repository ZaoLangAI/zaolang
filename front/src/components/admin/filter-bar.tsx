'use client';

import { useTranslations } from 'next-intl';

import { Button } from '@/components/ui/button';
import { DropdownMenu, DropdownMenuCheckboxItem } from '@/components/ui/dropdown-menu';
import { IconSearch } from '@/components/ui/icons';
import { cn } from '@/lib/cn';

export interface FilterDef {
  id: string;
  label: string;
  kind: 'text' | 'select' | 'multiselect' | 'daterange';
  options?: Array<{ value: string; label: string }>;
  placeholder?: string;
}

/** `daterange` filters split into two underlying filter keys: `${id}_after` / `${id}_before`. */
function dateRangeKeys(id: string): { after: string; before: string } {
  return { after: `${id}_after`, before: `${id}_before` };
}

/** `multiselect` stores its selection as one comma-joined string, same as
 * every other filter here — it stays a plain shareable query value instead
 * of needing its own array-shaped state. */
function parseMultiValue(raw: string | undefined): string[] {
  return (raw ?? '').split(',').filter(Boolean);
}

/**
 * Column filters for a console list.
 *
 * State lives in the parent as a plain record so it can be lifted straight into
 * a query string: a filtered view has to be shareable with the colleague who
 * asked about it.
 *
 * Passing `onSearch` switches the bar into "apply on demand" mode: an Enter
 * keypress in any text field also triggers it, and a search button appears
 * next to `children`. Omit it to keep the original "apply as you type"
 * behaviour other consoles rely on.
 */
export function FilterBar({
  filters,
  values,
  onChange,
  onReset,
  onSearch,
  children,
}: {
  filters: FilterDef[];
  values: Record<string, string>;
  onChange: (id: string, value: string) => void;
  onReset: () => void;
  onSearch?: () => void;
  children?: React.ReactNode;
}) {
  const t = useTranslations('admin');
  const dirty = Object.values(values).some((value) => value !== '');

  const handleKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'Enter' && onSearch) onSearch();
  };

  return (
    <div className="flex flex-wrap items-end gap-3 rounded-[var(--radius-md)] border border-border bg-surface p-3">
      {filters.map((filter) => {
        if (filter.kind === 'daterange') {
          const { after, before } = dateRangeKeys(filter.id);
          return (
            <label key={filter.id} className="flex flex-col gap-1 text-xs text-muted">
              {filter.label}
              <span className="flex items-center gap-1.5">
                <input
                  type="datetime-local"
                  value={values[after] ?? ''}
                  onChange={(event) => onChange(after, event.target.value)}
                  className="h-9 rounded-[var(--radius-sm)] border border-border bg-surface-soft px-2 text-xs text-text"
                />
                <span aria-hidden="true">–</span>
                <input
                  type="datetime-local"
                  value={values[before] ?? ''}
                  onChange={(event) => onChange(before, event.target.value)}
                  className="h-9 rounded-[var(--radius-sm)] border border-border bg-surface-soft px-2 text-xs text-text"
                />
              </span>
            </label>
          );
        }

        if (filter.kind === 'multiselect') {
          const selected = parseMultiValue(values[filter.id]);
          const toggle = (value: string) => {
            const next = selected.includes(value)
              ? selected.filter((item) => item !== value)
              : [...selected, value];
            onChange(filter.id, next.join(','));
          };
          const triggerLabel =
            selected.length > 0 ? `${filter.label} (${selected.length})` : filter.label;
          return (
            <div key={filter.id} className="flex flex-col gap-1 text-xs text-muted">
              <span className="pl-0.5">{filter.label}</span>
              <DropdownMenu
                triggerIcon={null}
                triggerLabel={triggerLabel}
                ariaLabel={filter.label}
                align="start"
                width="w-56"
              >
                {filter.options?.map((option) => (
                  <DropdownMenuCheckboxItem
                    key={option.value}
                    checked={selected.includes(option.value)}
                    onToggle={() => toggle(option.value)}
                  >
                    {option.label}
                  </DropdownMenuCheckboxItem>
                ))}
              </DropdownMenu>
            </div>
          );
        }

        return (
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
                  onKeyDown={handleKeyDown}
                  className={cn(
                    'h-9 w-48 rounded-[var(--radius-sm)] border border-border bg-surface-soft pl-8 pr-2.5 text-sm text-text',
                    'placeholder:text-muted/70',
                  )}
                />
              </span>
            )}
          </label>
        );
      })}

      {dirty ? (
        <Button size="sm" variant="ghost" onClick={onReset}>
          {t('reset')}
        </Button>
      ) : null}

      {onSearch ? (
        <Button size="sm" variant="primary" icon={<IconSearch />} onClick={onSearch}>
          {t('search')}
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
