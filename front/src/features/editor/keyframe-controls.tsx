'use client';

import { useTranslations } from 'next-intl';
import { useState } from 'react';

import { Button } from '@/components/ui/button';

import { resolveNumberAtTime } from './engine/animation';
import {
  TICKS_PER_SECOND,
  type AnimatableProperty,
  type EasingType,
  type EditCommand,
  type ElementAnimations,
} from './engine/ports';
import { useEditorUi } from './store';

const EASING_OPTIONS: EasingType[] = ['linear', 'ease_in', 'ease_out'];

interface PropertyConfig {
  property: AnimatableProperty;
  label: string;
  defaultValue: number;
  min: number;
  max: number;
  step: number;
  /** Converts the stored millis/millidegree value to what the number input shows, and back. */
  toDisplay: (value: number) => number;
  fromDisplay: (display: number) => number;
}

function propertyConfigs(
  t: (
    key:
      | 'keyframeOpacity'
      | 'keyframeX'
      | 'keyframeY'
      | 'keyframeScale'
      | 'keyframeRotation'
      | 'keyframeVolume',
  ) => string,
  baseVolumeMillipercent: number,
): PropertyConfig[] {
  return [
    {
      property: 'opacity',
      label: t('keyframeOpacity'),
      defaultValue: 100_000,
      min: 0,
      max: 100,
      step: 1,
      toDisplay: (v) => Math.round(v / 1_000),
      fromDisplay: (d) => d * 1_000,
    },
    {
      property: 'transform.x_milli',
      label: t('keyframeX'),
      defaultValue: 0,
      min: -200,
      max: 200,
      step: 1,
      toDisplay: (v) => Math.round(v / 10),
      fromDisplay: (d) => d * 10,
    },
    {
      property: 'transform.y_milli',
      label: t('keyframeY'),
      defaultValue: 0,
      min: -200,
      max: 200,
      step: 1,
      toDisplay: (v) => Math.round(v / 10),
      fromDisplay: (d) => d * 10,
    },
    {
      property: 'transform.scale_millipercent',
      label: t('keyframeScale'),
      defaultValue: 100_000,
      min: 10,
      max: 500,
      step: 1,
      toDisplay: (v) => Math.round(v / 1_000),
      fromDisplay: (d) => d * 1_000,
    },
    {
      property: 'transform.rotation_millidegrees',
      label: t('keyframeRotation'),
      defaultValue: 0,
      min: -180,
      max: 180,
      step: 1,
      toDisplay: (v) => Math.round(v / 1_000),
      fromDisplay: (d) => d * 1_000,
    },
    {
      property: 'volume',
      label: t('keyframeVolume'),
      // Same dimension `set_clip_volume` uses — a fresh channel should start
      // from the clip's current static volume, not an arbitrary default.
      defaultValue: baseVolumeMillipercent,
      min: 0,
      max: 200,
      step: 1,
      toDisplay: (v) => Math.round(v / 1_000),
      fromDisplay: (d) => d * 1_000,
    },
  ];
}

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
  baseVolumeMillipercent,
  disabled,
  onCommit,
}: {
  elementId: string;
  initialAnimations: ElementAnimations;
  baseVolumeMillipercent: number;
  disabled: boolean;
  onCommit: (commands: EditCommand[]) => void;
}) {
  const t = useTranslations('editor');
  const properties = propertyConfigs(t, baseVolumeMillipercent);
  const playheadTicks = useEditorUi((state) => state.playheadTicks);
  const [animations, setAnimations] = useState(initialAnimations);
  const [drafts, setDrafts] = useState<Partial<Record<AnimatableProperty, number>>>({});
  const [easingDrafts, setEasingDrafts] = useState<Partial<Record<AnimatableProperty, EasingType>>>(
    {},
  );

  const addKeyframe = (config: PropertyConfig) => {
    const resolved = resolveNumberAtTime(
      animations,
      config.property,
      playheadTicks,
      config.defaultValue,
    );
    const display = drafts[config.property] ?? config.toDisplay(resolved);
    const value = Math.round(config.fromDisplay(display));
    const easing = easingDrafts[config.property] ?? 'linear';
    onCommit([
      {
        type: 'set_keyframe',
        element_id: elementId,
        property: config.property,
        at_ticks: playheadTicks,
        value,
        easing,
      },
    ]);
    setAnimations((current) => {
      const existing = current.channels[config.property]?.points ?? [];
      const points = [
        ...existing.filter((point) => point.at_ticks !== playheadTicks),
        { at_ticks: playheadTicks, value, easing },
      ].sort((a, b) => a.at_ticks - b.at_ticks);
      return { channels: { ...current.channels, [config.property]: { kind: 'number', points } } };
    });
  };

  const deleteKeyframe = (property: AnimatableProperty, atTicks: number) => {
    onCommit([{ type: 'delete_keyframe', element_id: elementId, property, at_ticks: atTicks }]);
    setAnimations((current) => {
      const points = (current.channels[property]?.points ?? []).filter(
        (point) => point.at_ticks !== atTicks,
      );
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
      {properties.map((config) => {
        const points = animations.channels[config.property]?.points ?? [];
        const resolved = resolveNumberAtTime(
          animations,
          config.property,
          playheadTicks,
          config.defaultValue,
        );
        const draft = drafts[config.property] ?? config.toDisplay(resolved);
        return (
          <div key={config.property} className="flex flex-col gap-1">
            <div className="flex items-center gap-2">
              <label className="flex flex-1 items-center gap-2">
                {config.label}
                <input
                  type="number"
                  min={config.min}
                  max={config.max}
                  step={config.step}
                  value={draft}
                  disabled={disabled}
                  onChange={(event) =>
                    setDrafts((current) => ({
                      ...current,
                      [config.property]: Number(event.target.value),
                    }))
                  }
                  className="w-16 rounded-[var(--radius-sm)] border border-border bg-surface-soft px-1 py-0.5 text-fg"
                />
              </label>
              <select
                value={easingDrafts[config.property] ?? 'linear'}
                disabled={disabled}
                onChange={(event) =>
                  setEasingDrafts((current) => ({
                    ...current,
                    [config.property]: event.target.value as EasingType,
                  }))
                }
                aria-label={t('keyframeEasing')}
                className="rounded-[var(--radius-sm)] border border-border bg-surface-soft px-1 py-0.5 text-fg"
              >
                {EASING_OPTIONS.map((easing) => (
                  <option key={easing} value={easing}>
                    {t(
                      `keyframeEasing_${easing}` as
                        | 'keyframeEasing_linear'
                        | 'keyframeEasing_ease_in'
                        | 'keyframeEasing_ease_out',
                    )}
                  </option>
                ))}
              </select>
              <Button
                size="sm"
                variant="secondary"
                disabled={disabled}
                onClick={() => addKeyframe(config)}
              >
                {t('keyframeAdd')}
              </Button>
              {points.length > 0 ? (
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={disabled}
                  onClick={() => clearKeyframes(config.property)}
                >
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
