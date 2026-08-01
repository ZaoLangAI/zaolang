'use client';

import { useId } from 'react';

import { cn } from '@/lib/cn';

export interface Option<T extends string | number> {
  value: T;
  label: string;
  hint?: string;
  trailing?: string;
  icon?: React.ReactNode;
}

/**
 * Segmented single-choice control used throughout the studio.
 *
 * A radio group rather than buttons: arrow keys move between options and the
 * chosen value is announced, which a row of `aria-pressed` buttons does not
 * give you.
 */
export function OptionGroup<T extends string | number>({
  label,
  options,
  value,
  onChange,
  columns = 3,
  disabled,
}: {
  label: string;
  options: Array<Option<T>>;
  value: T;
  onChange: (value: T) => void;
  columns?: 2 | 3;
  disabled?: boolean;
}) {
  const name = useId();

  return (
    <fieldset disabled={disabled}>
      <legend className="mb-2 text-xs text-muted">{label}</legend>
      <div
        role="radiogroup"
        aria-label={label}
        className={cn('grid gap-2', columns === 2 ? 'grid-cols-2' : 'grid-cols-3')}
      >
        {options.map((option) => {
          const selected = option.value === value;
          return (
            <label
              key={String(option.value)}
              className={cn(
                'flex cursor-pointer flex-col gap-0.5 rounded-[var(--radius-sm)] border px-3 py-2.5 text-center transition-colors',
                'focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-[var(--focus)]',
                selected
                  ? 'border-primary bg-primary/10 text-text'
                  : 'border-border text-muted hover:border-border-strong hover:text-text',
                disabled && 'cursor-not-allowed opacity-50',
              )}
            >
              <input
                type="radio"
                name={name}
                className="sr-only"
                checked={selected}
                onChange={() => onChange(option.value)}
              />
              <span className="flex items-center justify-center gap-1.5 text-sm">
                {option.icon}
                {option.label}
              </span>
              {option.hint ? <span className="text-[11px] text-muted">{option.hint}</span> : null}
              {option.trailing ? (
                <span className={cn('tabular text-[11px]', selected ? 'text-amber' : 'text-muted')}>
                  {option.trailing}
                </span>
              ) : null}
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}
