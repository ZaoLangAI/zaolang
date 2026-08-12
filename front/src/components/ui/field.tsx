'use client';

import { forwardRef, useEffect, useId, useRef, useState } from 'react';

import { cn } from '@/lib/cn';

const controlBase =
  'w-full rounded-[var(--radius-sm)] border bg-surface-soft px-3 text-text placeholder:text-muted/70 ' +
  'transition-colors disabled:cursor-not-allowed disabled:opacity-60 ' +
  'aria-[invalid=true]:border-danger';

type FieldLayout = 'stacked' | 'inline';

interface FieldShellProps {
  label: string;
  hint?: string;
  error?: string;
  required?: boolean;
  /** `inline`: label beside control; hint sits above the control in the value column. */
  layout?: FieldLayout;
  children: (ids: { controlId: string; describedBy: string | undefined }) => React.ReactNode;
}

/**
 * Wires label, hint and error to the control.
 *
 * The error is announced rather than only coloured, which is what makes the
 * form usable without sight and with a red-green colour deficiency.
 */
export function Field({
  label,
  hint,
  error,
  required,
  layout = 'stacked',
  children,
}: FieldShellProps) {
  const controlId = useId();
  const hintId = `${controlId}-hint`;
  const errorId = `${controlId}-error`;
  const describedBy = [hint ? hintId : null, error ? errorId : null].filter(Boolean).join(' ');
  const labelNode = (
    <label htmlFor={controlId} className="text-sm font-medium text-text">
      {label}
      {required ? (
        <span className="ml-1 text-danger" aria-hidden="true">
          *
        </span>
      ) : null}
    </label>
  );
  const hintNode = hint ? (
    <p id={hintId} className="text-xs leading-relaxed text-muted">
      {hint}
    </p>
  ) : null;
  const errorNode = error ? (
    <p id={errorId} role="alert" className="text-xs text-danger">
      {error}
    </p>
  ) : null;
  const control = children({ controlId, describedBy: describedBy || undefined });

  if (layout === 'inline') {
    return (
      <div className="grid grid-cols-[6.5rem_minmax(0,1fr)] items-start gap-x-3 gap-y-1 sm:grid-cols-[7.5rem_minmax(0,1fr)]">
        {hintNode ? <div className="col-start-2 row-start-1">{hintNode}</div> : null}
        <div
          className={cn(
            'col-start-1 flex min-h-11 items-center',
            hintNode ? 'row-start-2' : 'row-start-1',
          )}
        >
          {labelNode}
        </div>
        <div className={cn('col-start-2 min-w-0', hintNode ? 'row-start-2' : 'row-start-1')}>
          {control}
        </div>
        {errorNode ? (
          <div className={cn('col-start-2', hintNode ? 'row-start-3' : 'row-start-2')}>
            {errorNode}
          </div>
        ) : null}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-1.5">
      {labelNode}
      {hintNode}
      {control}
      {errorNode}
    </div>
  );
}

export interface TextInputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  label: string;
  hint?: string;
  error?: string;
  layout?: FieldLayout;
}

export const TextInput = forwardRef<HTMLInputElement, TextInputProps>(function TextInput(
  { label, hint, error, layout, className, required, ...rest },
  ref,
) {
  return (
    <Field label={label} hint={hint} error={error} required={required} layout={layout}>
      {({ controlId, describedBy }) => (
        <input
          ref={ref}
          id={controlId}
          aria-describedby={describedBy}
          aria-invalid={error ? true : undefined}
          required={required}
          className={cn(controlBase, 'h-11', className)}
          {...rest}
        />
      )}
    </Field>
  );
});

export interface TextAreaProps extends React.TextareaHTMLAttributes<HTMLTextAreaElement> {
  label: string;
  hint?: string;
  error?: string;
  layout?: FieldLayout;
}

export const TextArea = forwardRef<HTMLTextAreaElement, TextAreaProps>(function TextArea(
  { label, hint, error, layout, className, required, ...rest },
  ref,
) {
  return (
    <Field label={label} hint={hint} error={error} required={required} layout={layout}>
      {({ controlId, describedBy }) => (
        <textarea
          ref={ref}
          id={controlId}
          aria-describedby={describedBy}
          aria-invalid={error ? true : undefined}
          required={required}
          className={cn(controlBase, 'min-h-28 resize-y py-2.5 leading-relaxed', className)}
          {...rest}
        />
      )}
    </Field>
  );
});

export interface SelectProps extends React.SelectHTMLAttributes<HTMLSelectElement> {
  label: string;
  hint?: string;
  error?: string;
  layout?: FieldLayout;
  options: Array<{ value: string; label: string; disabled?: boolean }>;
}

export const Select = forwardRef<HTMLSelectElement, SelectProps>(function Select(
  { label, hint, error, layout, options, className, required, ...rest },
  ref,
) {
  return (
    <Field label={label} hint={hint} error={error} required={required} layout={layout}>
      {({ controlId, describedBy }) => (
        <select
          ref={ref}
          id={controlId}
          aria-describedby={describedBy}
          aria-invalid={error ? true : undefined}
          required={required}
          className={cn(controlBase, 'h-11 appearance-none pr-8', className)}
          {...rest}
        >
          {options.map((option) => (
            <option key={option.value} value={option.value} disabled={option.disabled}>
              {option.label}
            </option>
          ))}
        </select>
      )}
    </Field>
  );
});

export interface MultiSelectProps {
  label: string;
  hint?: string;
  error?: string;
  layout?: FieldLayout;
  value: string[];
  onChange: (next: string[]) => void;
  options: Array<{ value: string; label: string }>;
  placeholder?: string;
  emptyHint?: string;
  disabled?: boolean;
}

/**
 * A dropdown checkbox list, for choosing zero or more of a small option set.
 *
 * Native `<select multiple>` needs a modifier key per pick and shows an
 * awkward fixed-height listbox, so this is a button that opens a popover
 * instead — closer to what "multi-select dropdown" means to most people.
 */
export function MultiSelect({
  label,
  hint,
  error,
  layout,
  value,
  onChange,
  options,
  placeholder,
  emptyHint,
  disabled,
}: MultiSelectProps) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', onPointerDown);
    return () => document.removeEventListener('mousedown', onPointerDown);
  }, [open]);

  const toggle = (optionValue: string) =>
    onChange(
      value.includes(optionValue)
        ? value.filter((item) => item !== optionValue)
        : [...value, optionValue],
    );

  const summary = value
    .map((item) => options.find((option) => option.value === item)?.label ?? item)
    .join('、');
  const isDisabled = disabled || options.length === 0;

  return (
    <Field label={label} hint={hint} error={error} layout={layout}>
      {({ controlId, describedBy }) => (
        <div ref={rootRef} className="relative">
          <button
            type="button"
            id={controlId}
            aria-describedby={describedBy}
            aria-haspopup="listbox"
            aria-expanded={open}
            disabled={isDisabled}
            onClick={() => setOpen((current) => !current)}
            className={cn(
              controlBase,
              'flex h-11 items-center justify-between gap-2 text-left',
              !summary && 'text-muted/70',
              error && 'border-danger',
            )}
          >
            <span className="min-w-0 flex-1 truncate">
              {summary || (options.length === 0 ? emptyHint : placeholder)}
            </span>
            {value.length > 0 ? (
              <span className="shrink-0 text-xs text-muted">{value.length}</span>
            ) : null}
          </button>
          {open ? (
            <ul
              role="listbox"
              aria-multiselectable="true"
              className="absolute z-10 mt-1 max-h-60 w-full overflow-auto rounded-[var(--radius-sm)] border border-border bg-surface-raised py-1 shadow-raised"
            >
              {options.map((option) => (
                <li key={option.value}>
                  <label className="flex cursor-pointer items-center gap-2 px-3 py-2 text-sm text-text hover:bg-surface-soft">
                    <input
                      type="checkbox"
                      checked={value.includes(option.value)}
                      onChange={() => toggle(option.value)}
                    />
                    {option.label}
                  </label>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      )}
    </Field>
  );
}

/** Labelled switch. The label is clickable and the state is programmatic. */
export function Switch({
  checked,
  onChange,
  label,
  description,
  disabled,
  compact = false,
  className,
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  label: string;
  description?: string;
  disabled?: boolean;
  /** Icon-toolbar rendering: just the toggle, sized to sit among icon
   * buttons instead of a full label row. `label` still becomes the
   * accessible name and hover tooltip — there's no room for visible text
   * next to it in a dense action row. */
  compact?: boolean;
  /** Only applied in `compact` mode, e.g. `ml-auto` to group it with the
   * delete button at the end of an action row. */
  className?: string;
}) {
  const id = useId();
  const descriptionId = `${id}-description`;

  if (compact) {
    return (
      <button
        id={id}
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={label}
        title={label}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={cn(
          'relative h-5 w-9 shrink-0 rounded-full transition-colors disabled:cursor-not-allowed disabled:opacity-50',
          checked ? 'bg-primary' : 'bg-track',
          className,
        )}
      >
        <span
          aria-hidden="true"
          className={cn(
            'absolute top-0.5 size-4 rounded-full bg-white shadow transition-[left]',
            checked ? 'left-[18px]' : 'left-0.5',
          )}
        />
      </button>
    );
  }

  return (
    <div className="flex items-start justify-between gap-6 py-3">
      <div className="min-w-0">
        <label htmlFor={id} className="block text-sm font-medium text-text">
          {label}
        </label>
        {description ? (
          <p id={descriptionId} className="mt-0.5 text-xs text-muted">
            {description}
          </p>
        ) : null}
      </div>
      <button
        id={id}
        type="button"
        role="switch"
        aria-checked={checked}
        aria-describedby={description ? descriptionId : undefined}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={cn(
          'relative mt-0.5 h-6 w-11 shrink-0 rounded-full transition-colors disabled:opacity-50',
          checked ? 'bg-primary' : 'bg-track',
        )}
      >
        <span
          aria-hidden="true"
          className={cn(
            'absolute top-0.5 size-5 rounded-full bg-white shadow transition-[left]',
            checked ? 'left-[22px]' : 'left-0.5',
          )}
        />
      </button>
    </div>
  );
}
