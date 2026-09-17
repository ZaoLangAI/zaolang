'use client';

import { useTranslations } from 'next-intl';
import { useRef, useState } from 'react';

import { IconResetValue } from '@/components/ui/icons';
import { cn } from '@/lib/cn';

/**
 * Adapted from OpenCut's `PropertyItem`/`PropertyInput` numeric row: the
 * label doubles as a horizontal scrub handle (drag left/right to change the
 * value, Shift ×10), the box commits on Enter/blur and reverts on Escape,
 * and a reset glyph appears whenever the value differs from its default.
 *
 * Values are displayed in user units (`display`) but committed in the
 * document's integer milli-units — the caller supplies both conversions.
 */
export function NumberField({
  label,
  value,
  defaultValue,
  min,
  max,
  step = 1,
  precision = 0,
  unit,
  disabled,
  onCommit,
  className,
}: {
  label: string;
  /** Current value in display units. */
  value: number;
  /** Shown as the reset target; the reset glyph is hidden while `value === defaultValue`. */
  defaultValue: number;
  min: number;
  max: number;
  /** Display-unit change per pixel of label drag, and the keyboard arrow increment. */
  step?: number;
  precision?: number;
  unit?: string;
  disabled?: boolean;
  onCommit: (value: number) => void;
  className?: string;
}) {
  const t = useTranslations('editor');
  // `draft` is only authoritative while the user is typing or scrubbing;
  // otherwise the box mirrors the committed `value`, so a server-side
  // clamp or an undo shows up without an effect re-syncing local state.
  const [draftState, setDraftState] = useState<string | null>(null);
  const revertRef = useRef(false);
  const dragRef = useRef<{ startX: number; startValue: number; moved: boolean } | null>(null);
  const draft = draftState ?? value.toFixed(precision);
  const setDraft = (next: string | null) => setDraftState(next);

  const clamp = (raw: number) => Math.min(max, Math.max(min, raw));
  const commit = (raw: number) => {
    setDraft(null);
    if (!Number.isFinite(raw)) return;
    const next = Number(clamp(raw).toFixed(precision));
    if (next !== value) onCommit(next);
  };

  const onLabelPointerDown = (event: React.PointerEvent<HTMLSpanElement>) => {
    if (disabled || event.button !== 0) return;
    event.preventDefault();
    dragRef.current = { startX: event.clientX, startValue: value, moved: false };
    event.currentTarget.setPointerCapture(event.pointerId);
  };
  const onLabelPointerMove = (event: React.PointerEvent<HTMLSpanElement>) => {
    const drag = dragRef.current;
    if (!drag) return;
    const delta = event.clientX - drag.startX;
    if (!drag.moved && Math.abs(delta) < 3) return;
    drag.moved = true;
    const multiplier = event.shiftKey ? 10 : 1;
    setDraft(clamp(drag.startValue + delta * step * multiplier).toFixed(precision));
  };
  const onLabelPointerUp = (event: React.PointerEvent<HTMLSpanElement>) => {
    const drag = dragRef.current;
    dragRef.current = null;
    if (!drag) return;
    event.currentTarget.releasePointerCapture(event.pointerId);
    if (!drag.moved) return;
    const multiplier = event.shiftKey ? 10 : 1;
    commit(drag.startValue + (event.clientX - drag.startX) * step * multiplier);
  };

  const isDefault = Math.abs(value - defaultValue) < 10 ** -precision / 2;

  return (
    <div className={cn('flex items-center gap-2 text-xs', className)}>
      <span
        onPointerDown={onLabelPointerDown}
        onPointerMove={onLabelPointerMove}
        onPointerUp={onLabelPointerUp}
        onPointerCancel={() => {
          dragRef.current = null;
          setDraft(null);
        }}
        title={disabled ? undefined : t('numberFieldDragHint')}
        className={cn(
          'w-16 shrink-0 select-none truncate text-muted',
          !disabled && 'cursor-ew-resize hover:text-text',
        )}
      >
        {label}
      </span>
      <div className="relative min-w-0 flex-1">
        <input
          type="text"
          inputMode="decimal"
          value={draft}
          disabled={disabled}
          aria-label={label}
          onChange={(event) => setDraft(event.target.value)}
          onFocus={() => {
            revertRef.current = false;
          }}
          onBlur={() => {
            if (revertRef.current) {
              revertRef.current = false;
              setDraft(null);
              return;
            }
            commit(Number(draft));
          }}
          onKeyDown={(event) => {
            if (event.key === 'Enter') {
              commit(Number(draft));
              event.currentTarget.blur();
            } else if (event.key === 'Escape') {
              // Revert first so the follow-up blur commits nothing new; the
              // flag covers the case where blur fires before React re-renders.
              revertRef.current = true;
              setDraft(null);
              event.currentTarget.blur();
            } else if (event.key === 'ArrowUp' || event.key === 'ArrowDown') {
              event.preventDefault();
              const direction = event.key === 'ArrowUp' ? 1 : -1;
              const multiplier = event.shiftKey ? 10 : 1;
              commit(Number(draft) + direction * step * multiplier);
            }
          }}
          className={cn(
            'h-7 w-full rounded-[var(--radius-sm)] border border-border bg-surface px-2 font-mono text-xs text-text outline-none focus:border-primary disabled:opacity-60',
            unit && 'pr-7',
          )}
        />
        {unit ? (
          <span className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 text-[10px] text-muted">
            {unit}
          </span>
        ) : null}
      </div>
      <button
        type="button"
        aria-label={t('numberFieldReset')}
        title={t('numberFieldReset')}
        disabled={disabled || isDefault}
        onClick={() => commit(defaultValue)}
        className={cn(
          'grid size-6 shrink-0 place-items-center rounded text-muted transition-opacity hover:text-text',
          isDefault ? 'opacity-0' : 'opacity-100',
        )}
      >
        <IconResetValue className="size-3.5" />
      </button>
    </div>
  );
}
