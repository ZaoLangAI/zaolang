'use client';

import { useTranslations } from 'next-intl';
import { useState } from 'react';

import { Button } from '@/components/ui/button';

import { TICKS_PER_SECOND, type ClipTransition, type EditCommand, type TransitionType } from './engine/ports';

const TRANSITION_TYPES: TransitionType[] = ['crossfade', 'dip_to_black'];

/**
 * A transition is never a new element or track — it's a property on this
 * clip's own start/end edge, realized only once the adjacent clip on the
 * same track actually overlaps it in time (via ordinary trim/move). This
 * panel just records the intent; `compositor.ts`'s `resolveOverlap` is what
 * turns two overlapping clips plus a configured edge into an actual blend.
 */
export function TransitionControls({
  elementId,
  durationTicks,
  initialTransitionIn,
  initialTransitionOut,
  disabled,
  onCommit,
}: {
  elementId: string;
  durationTicks: number;
  initialTransitionIn: ClipTransition | null;
  initialTransitionOut: ClipTransition | null;
  disabled: boolean;
  onCommit: (commands: EditCommand[]) => void;
}) {
  const t = useTranslations('editor');
  const maxSeconds = Math.max(0.1, durationTicks / TICKS_PER_SECOND);

  return (
    <div className="flex flex-col gap-3 border-t border-border pt-3 text-xs text-muted">
      <p className="text-sm font-semibold text-fg">{t('transitionsTitle')}</p>
      <EdgeControls
        label={t('transitionIn')}
        elementId={elementId}
        edge="in"
        initial={initialTransitionIn}
        maxSeconds={maxSeconds}
        disabled={disabled}
        onCommit={onCommit}
      />
      <EdgeControls
        label={t('transitionOut')}
        elementId={elementId}
        edge="out"
        initial={initialTransitionOut}
        maxSeconds={maxSeconds}
        disabled={disabled}
        onCommit={onCommit}
      />
    </div>
  );
}

function EdgeControls({
  label,
  elementId,
  edge,
  initial,
  maxSeconds,
  disabled,
  onCommit,
}: {
  label: string;
  elementId: string;
  edge: 'in' | 'out';
  initial: ClipTransition | null;
  maxSeconds: number;
  disabled: boolean;
  onCommit: (commands: EditCommand[]) => void;
}) {
  const t = useTranslations('editor');
  const transitionLabel: Record<TransitionType, string> = {
    crossfade: t('transitionType.crossfade'),
    dip_to_black: t('transitionType.dip_to_black'),
  };
  const [type, setType] = useState<TransitionType | 'none'>(initial?.type ?? 'none');
  const [seconds, setSeconds] = useState(initial ? initial.duration_ticks / TICKS_PER_SECOND : Math.min(1, maxSeconds));

  const apply = () => {
    const transition: ClipTransition | null =
      type === 'none' ? null : { type, duration_ticks: Math.round(Math.min(seconds, maxSeconds) * TICKS_PER_SECOND) };
    onCommit([{ type: 'set_transition', element_id: elementId, edge, transition }]);
  };

  return (
    <div className="flex flex-col gap-1">
      <p className="text-fg">{label}</p>
      <div className="flex items-center gap-2">
        <select
          value={type}
          disabled={disabled}
          onChange={(event) => setType(event.target.value as TransitionType | 'none')}
          className="rounded-[var(--radius-sm)] border border-border bg-surface-soft px-1.5 py-1 text-fg"
        >
          <option value="none">{t('transitionNone')}</option>
          {TRANSITION_TYPES.map((option) => (
            <option key={option} value={option}>
              {transitionLabel[option]}
            </option>
          ))}
        </select>
        {type !== 'none' ? (
          <input
            type="number"
            min={0.1}
            max={maxSeconds}
            step={0.1}
            value={seconds}
            disabled={disabled}
            onChange={(event) => setSeconds(Number(event.target.value))}
            className="w-16 rounded-[var(--radius-sm)] border border-border bg-surface-soft px-1 py-1 text-fg"
          />
        ) : null}
        <Button size="sm" variant="secondary" disabled={disabled} onClick={apply}>
          {t('transitionApply')}
        </Button>
      </div>
    </div>
  );
}
