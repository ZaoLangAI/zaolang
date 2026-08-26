'use client';

import { useTranslations } from 'next-intl';
import { useState } from 'react';

import { Button } from '@/components/ui/button';

import { resolveNumberAtTime } from './engine/animation';
import {
  TICKS_PER_SECOND,
  type AnimatableProperty,
  type EditCommand,
  type ElementAnimations,
} from './engine/ports';
import { useEditorUi } from './store';

interface PropertyConfig {
  property: AnimatableProperty;
  labelKey: string;
  defaultValue: number;
  min: number;
  max: number;
  step: number;
  /** Converts the stored millis/millidegree value to what the number input shows, and back. */
  toDisplay: (value: number) => number;
  fromDisplay: (display: number) => number;
}

const PROPERTIES: PropertyConfig[] = [
  {
    property: 'opacity',
    labelKey: 'keyframeOpacity',
    defaultValue: 100_000,
    min: 0,
    max: 100,
    step: 1,
    toDisplay: (v) => Math.round(v / 1_000),
    fromDisplay: (d) => d * 1_000,
  },
  {
    property: 'transform.x_milli',
    labelKey: 'keyframeX',
    defaultValue: 0,
    min: -200,
    max: 200,
    step: 1,
    toDisplay: (v) => Math.round(v / 10),
    fromDisplay: (d) => d * 10,
  },
  {
    property: 'transform.y_milli',
    labelKey: 'keyframeY',
    defaultValue: 0,
    min: -200,
    max: 200,
    step: 1,
    toDisplay: (v) => Math.round(v / 10),
    fromDisplay: (d) => d * 10,
  },
  {
    property: 'transform.scale_millipercent',
    labelKey: 'keyframeScale',
    defaultValue: 100_000,
    min: 10,
    max: 500,
    step: 1,
    toDisplay: (v) => Math.round(v / 1_000),
    fromDisplay: (d) => d * 1_000,
  },
  {
    property: 'transform.rotation_millidegrees',
    labelKey: 'keyframeRotation',
    defaultValue: 0,
    min: -180,
    max: 180,
    step: 1,
    toDisplay: (v) => Math.round(v / 1_000),
    fromDisplay: (d) => d * 1_000,
  },
];

function secondsLabel(ticks: number): string {
  return `${(ticks / TICKS_PER_SECOND).toFixed(1)}s`;
}

/**
 * Coarse, hand-placed keyframes for opacity and transform — not per-frame
 * animation. "打关键帧" captures the property's value *at the current
 * playhead* (resolved the same way the compositor would, via
 * `resolveNumberAtTime`) so a first keyframe starts from what's already
 * showing rather than a blank default.
 */
export function KeyframeControls({
  elementId,
  initialAnimations,
  disabled,
  onCommit,
}: {
  elementId: string;
  initialAnimations: ElementAnimations;
  disabled: boolean;
  onCommit: (commands: EditCommand[]) => void;
}) {
  const t = useTranslations('editor');
  const playheadTicks = useEditorUi((state) => state.playheadTicks);
  const [animations, setAnimations] = useState(initialAnimations);
  const [drafts, setDrafts] = useState<Partial<Record<AnimatableProperty, number>>>({});

  const addKeyframe = (config: PropertyConfig) => {
    const resolved = resolveNumberAtTime(animations, config.property, playheadTicks, config.defaultValue);
    const display = drafts[config.property] ?? config.toDisplay(resolved);
    const value = Math.round(config.fromDisplay(display));
    onCommit([{ type: 'set_keyframe', element_id: elementId, property: config.property, at_ticks: playheadTicks, value }]);
    setAnimations((current) => {
      const existing = current.channels[config.property]?.points ?? [];
      const points = [...existing.filter((point) => point.at_ticks !== playheadTicks), { at_ticks: playheadTicks, value }].sort(
        (a, b) => a.at_ticks - b.at_ticks,
      );
      return { channels: { ...current.channels, [config.property]: { kind: 'number', points } } };
    });
  };

  const deleteKeyframe = (property: AnimatableProperty, atTicks: number) => {
    onCommit([{ type: 'delete_keyframe', element_id: elementId, property, at_ticks: atTicks }]);
    setAnimations((current) => {
      const points = (current.channels[property]?.points ?? []).filter((point) => point.at_ticks !== atTicks);
      return { channels: { ...current.channels, [property]: { kind: 'number', points } } };
    });
  };

  const clearKeyframes = (property: AnimatableProperty) => {
    onCommit([{ type: 'clear_keyframes', element_id: elementId, property }]);
    setAnimations((current) => {
      const next = { ...current.channels };
      delete next[property];
      return { channels: next };
    });
  };

  return (
    <div className="flex flex-col gap-3 border-t border-border pt-3 text-xs text-muted">
      <p className="text-sm font-semibold text-fg">{t('keyframesTitle')}</p>
      <p className="text-xs text-muted">{t('keyframesHint')}</p>
      {PROPERTIES.map((config) => {
        const points = animations.channels[config.property]?.points ?? [];
        const resolved = resolveNumberAtTime(animations, config.property, playheadTicks, config.defaultValue);
        const draft = drafts[config.property] ?? config.toDisplay(resolved);
        return (
          <div key={config.property} className="flex flex-col gap-1">
            <div className="flex items-center gap-2">
              <label className="flex flex-1 items-center gap-2">
                {t(config.labelKey)}
                <input
                  type="number"
                  min={config.min}
                  max={config.max}
                  step={config.step}
                  value={draft}
                  disabled={disabled}
                  onChange={(event) =>
                    setDrafts((current) => ({ ...current, [config.property]: Number(event.target.value) }))
                  }
                  className="w-16 rounded-[var(--radius-sm)] border border-border bg-surface-soft px-1 py-0.5 text-fg"
                />
              </label>
              <Button size="sm" variant="secondary" disabled={disabled} onClick={() => addKeyframe(config)}>
                {t('keyframeAdd')}
              </Button>
              {points.length > 0 ? (
                <Button size="sm" variant="ghost" disabled={disabled} onClick={() => clearKeyframes(config.property)}>
                  {t('keyframeClearAll')}
                </Button>
              ) : null}
            </div>
            {points.length > 0 ? (
              <ul className="flex flex-wrap gap-1">
                {points.map((point) => (
                  <li
                    key={point.at_ticks}
                    className="flex items-center gap-1 rounded-[var(--radius-sm)] border border-border bg-surface-soft px-1.5 py-0.5"
                  >
                    {secondsLabel(point.at_ticks)}: {config.toDisplay(point.value)}
                    <button
                      type="button"
                      disabled={disabled}
                      onClick={() => deleteKeyframe(config.property, point.at_ticks)}
                      aria-label={t('keyframeDelete')}
                      className="text-muted hover:text-fg"
                    >
                      ×
                    </button>
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}
