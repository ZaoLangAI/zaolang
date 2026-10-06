'use client';

import { cn } from '@/lib/cn';

/** Multi-select chips — a checkbox group styled like `OptionGroup`. */
export function ChipGroup<T extends string>({
  label,
  options,
  selected,
  onToggle,
  max,
}: {
  label: string;
  options: { value: T; label: string }[];
  selected: T[];
  onToggle: (value: T) => void;
  max: number;
}) {
  return (
    <fieldset className="min-w-0">
      <legend className="mb-2 text-xs text-muted">{label}</legend>
      <div className="flex flex-wrap gap-1.5">
        {options.map((option) => {
          const checked = selected.includes(option.value);
          const disabled = !checked && selected.length >= max;
          return (
            <label
              key={option.value}
              className={cn(
                'cursor-pointer rounded-[var(--radius-sm)] border px-2.5 py-1.5 text-xs transition-colors',
                'focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-[var(--focus)]',
                checked
                  ? 'border-primary bg-primary/10 text-text'
                  : 'border-border text-muted hover:border-border-strong hover:text-text',
                disabled && 'cursor-not-allowed opacity-50',
              )}
            >
              <input
                type="checkbox"
                className="sr-only"
                checked={checked}
                disabled={disabled}
                onChange={() => onToggle(option.value)}
              />
              {option.label}
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}
