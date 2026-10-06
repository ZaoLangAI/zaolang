'use client';

import { useTranslations } from 'next-intl';
import { useState } from 'react';

import type { CameraPose } from '@/lib/api/types';
import { cn } from '@/lib/cn';

import {
  AZIMUTHS,
  DISTANCES,
  type Distance,
  ELEVATIONS,
  MAX_CAMERA_POSES,
  pose,
  poseKey,
} from './camera';

export type Coverage = Map<string, 'approved' | 'candidate'>;

/**
 * 角度盘: pick camera poses around the subject. Eight azimuth buttons on a
 * dial for the chosen elevation and distance; each shows whether that pose
 * is already filed (filled = 定稿, ring = 候选). Every pose is a toggle
 * button, so the whole control works from the keyboard.
 */
export function OrbitPicker({
  selected,
  onChange,
  coverage,
  disabled = false,
}: {
  selected: CameraPose[];
  onChange: (next: CameraPose[]) => void;
  coverage: Coverage;
  disabled?: boolean;
}) {
  const t = useTranslations('assetWorkspace');
  const [elevation, setElevation] = useState<number>(0);
  const [distance, setDistance] = useState<Distance>('medium');
  const keys = new Set(selected.map(poseKey));
  const full = selected.length >= MAX_CAMERA_POSES;

  const toggle = (azimuth: number) => {
    const next = pose(azimuth, elevation, distance);
    const key = poseKey(next);
    if (keys.has(key)) onChange(selected.filter((p) => poseKey(p) !== key));
    else if (!full) onChange([...selected, next]);
  };

  return (
    <div className="flex flex-col gap-3">
      <SegmentedChoice
        label={t('orbit.elevation')}
        value={String(elevation)}
        options={ELEVATIONS.map((value) => ({
          value: String(value),
          label: t(`elevation.${value}`),
        }))}
        onChange={(value) => setElevation(Number(value))}
      />
      <SegmentedChoice
        label={t('orbit.distance')}
        value={distance}
        options={DISTANCES.map((value) => ({ value, label: t(`distance.${value}`) }))}
        onChange={(value) => setDistance(value as Distance)}
      />
      <div
        role="group"
        aria-label={t('orbit.dialLabel')}
        className="relative mx-auto aspect-square w-full max-w-[240px]"
      >
        <div className="absolute inset-[18%] rounded-full border border-dashed border-border" />
        <span className="absolute inset-0 m-auto flex size-14 items-center justify-center rounded-full bg-surface-soft text-center text-[11px] text-muted">
          {t('orbit.subject')}
        </span>
        {AZIMUTHS.map((azimuth) => {
          const key = poseKey(pose(azimuth, elevation, distance));
          const on = keys.has(key);
          const filed = coverage.get(key);
          // 0° faces the camera at the bottom of the dial; 90° (the subject's
          // right) sits on the viewer's left.
          const angle = ((azimuth + 90) * Math.PI) / 180;
          const left = 50 + 40 * Math.cos(angle);
          const top = 50 + 40 * Math.sin(angle);
          return (
            <button
              key={azimuth}
              type="button"
              aria-pressed={on}
              disabled={disabled || (!on && full)}
              onClick={() => toggle(azimuth)}
              title={t(`azimuth.${azimuth}`)}
              style={{ left: `${left}%`, top: `${top}%` }}
              className={cn(
                'absolute flex size-11 -translate-x-1/2 -translate-y-1/2 flex-col items-center justify-center rounded-full border text-[10px] leading-tight transition-colors focus-visible:outline-2 disabled:opacity-40',
                on
                  ? 'border-primary bg-primary text-on-primary'
                  : filed === 'approved'
                    ? 'border-success bg-success/15 text-text'
                    : filed === 'candidate'
                      ? 'border-dashed border-amber text-text'
                      : 'border-border bg-surface text-muted hover:text-text',
              )}
            >
              <span>{azimuth}°</span>
              <span className="sr-only">
                {t(`azimuth.${azimuth}`)}
                {filed ? ` · ${t(`coverage.${filed}`)}` : ''}
              </span>
            </button>
          );
        })}
      </div>
      <p className="text-[11px] text-muted">{t('orbit.legend')}</p>
      {selected.length ? (
        <ul className="flex flex-wrap gap-1.5" aria-label={t('orbit.selected')}>
          {selected.map((value) => (
            <li key={poseKey(value)}>
              <button
                type="button"
                disabled={disabled}
                onClick={() => onChange(selected.filter((p) => poseKey(p) !== poseKey(value)))}
                className="rounded-full border border-border px-2 py-0.5 text-xs hover:border-danger focus-visible:outline-2"
              >
                {poseLabel(t, value)} ×
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

/** 「右侧 90°·平视·中景」 */
export function poseLabel(
  t: ReturnType<typeof useTranslations<'assetWorkspace'>>,
  value: CameraPose,
): string {
  const [azimuth, elevation, distance] = poseKey(value).split('|');
  return [
    t(`azimuth.${azimuth}` as 'azimuth.0'),
    t(`elevation.${elevation}` as 'elevation.0'),
    t(`distance.${distance}` as 'distance.medium'),
  ].join('·');
}

function SegmentedChoice({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: { value: string; label: string }[];
  onChange: (value: string) => void;
}) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-xs text-muted">{label}</span>
      <div role="radiogroup" aria-label={label} className="flex flex-wrap gap-1">
        {options.map((option) => (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={value === option.value}
            onClick={() => onChange(option.value)}
            className={cn(
              'rounded-[var(--radius-sm)] border px-2 py-1 text-xs focus-visible:outline-2',
              value === option.value
                ? 'border-primary bg-primary/10 text-text'
                : 'border-border text-muted hover:text-text',
            )}
          >
            {option.label}
          </button>
        ))}
      </div>
    </div>
  );
}
