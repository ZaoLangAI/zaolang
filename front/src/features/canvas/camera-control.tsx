'use client';

import { useTranslations } from 'next-intl';

import { Select } from '@/components/ui/field';
import { Switch } from '@/components/ui/field';

import {
  APERTURES,
  APERTURE_META,
  CAMERA_PROFILES,
  FOCAL_LENGTHS,
  FOCAL_LENGTH_META,
  LENS_PROFILES,
  type CameraControlOptions,
} from './canvas-camera';

export const DEFAULT_CAMERA_CONTROL: CameraControlOptions = {
  enabled: false,
  camera: CAMERA_PROFILES[0]?.id ?? '',
  lens: LENS_PROFILES[0]?.id ?? '',
  focalLength: 35,
  aperture: 2.8,
};

/** Reads a camera setting off a node's stored payload, filling any gap from
 * the default — a card authored before this panel existed has none of it. */
export function readCameraControl(
  payload: Record<string, unknown> | undefined,
): CameraControlOptions {
  const raw = payload?.camera;
  if (typeof raw !== 'object' || raw === null) return DEFAULT_CAMERA_CONTROL;
  const value = raw as Partial<CameraControlOptions>;
  return {
    enabled: value.enabled === true,
    camera: typeof value.camera === 'string' ? value.camera : DEFAULT_CAMERA_CONTROL.camera,
    lens: typeof value.lens === 'string' ? value.lens : DEFAULT_CAMERA_CONTROL.lens,
    focalLength:
      typeof value.focalLength === 'number'
        ? value.focalLength
        : DEFAULT_CAMERA_CONTROL.focalLength,
    aperture: typeof value.aperture === 'number' ? value.aperture : DEFAULT_CAMERA_CONTROL.aperture,
  };
}

/**
 * Lens direction for one prompt card.
 *
 * No model this platform routes to takes a focal length or an aperture as a
 * parameter, so these choices only ever reach a generation as prompt text
 * (`applyCameraPrompt`). The panel therefore reads as a set of creative
 * choices, not as request fields — and it is off by default, because folding
 * a page of optical language into every prompt would drown a simple one.
 */
export function CameraControl({
  value,
  onChange,
}: {
  value: CameraControlOptions;
  onChange: (next: CameraControlOptions) => void;
}) {
  const t = useTranslations('canvas');

  return (
    <div className="space-y-2 rounded-[var(--radius-sm)] border border-border p-2.5">
      <Switch
        label={t('cameraEnable')}
        checked={value.enabled}
        onChange={(enabled) => onChange({ ...value, enabled })}
      />
      {value.enabled ? (
        <>
          <Select
            label={t('cameraBody')}
            value={value.camera}
            onChange={(event) => onChange({ ...value, camera: event.target.value })}
            options={CAMERA_PROFILES.map((profile) => ({
              value: profile.id,
              label: `${profile.zhName} · ${profile.label}`,
            }))}
          />
          <Select
            label={t('cameraLens')}
            value={value.lens}
            onChange={(event) => onChange({ ...value, lens: event.target.value })}
            options={LENS_PROFILES.map((profile) => ({
              value: profile.id,
              label: `${profile.zhName} · ${profile.label}`,
            }))}
          />
          <Select
            label={t('cameraFocal')}
            value={String(value.focalLength)}
            onChange={(event) => onChange({ ...value, focalLength: Number(event.target.value) })}
            options={FOCAL_LENGTHS.map((mm) => ({
              value: String(mm),
              label: `${mm}mm · ${FOCAL_LENGTH_META[mm]?.zhName ?? ''}`,
            }))}
          />
          <Select
            label={t('cameraAperture')}
            value={String(value.aperture)}
            onChange={(event) => onChange({ ...value, aperture: Number(event.target.value) })}
            options={APERTURES.map((f) => ({
              value: String(f),
              label: `f/${f} · ${APERTURE_META[f]?.zhName ?? ''}`,
            }))}
          />
          <p className="text-[11px] text-muted">
            {FOCAL_LENGTH_META[value.focalLength]?.useCase}
            {' · '}
            {APERTURE_META[value.aperture]?.useCase}
          </p>
        </>
      ) : null}
    </div>
  );
}
