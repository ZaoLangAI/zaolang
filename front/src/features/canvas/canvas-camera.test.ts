import { describe, expect, it } from 'vitest';

import {
  APERTURES,
  APERTURE_META,
  CAMERA_PROFILES,
  FOCAL_LENGTHS,
  FOCAL_LENGTH_META,
  LENS_PROFILES,
  applyCameraPrompt,
  describeAperture,
  describeFocalLength,
  type CameraControlOptions,
} from './canvas-camera';

const on: CameraControlOptions = {
  enabled: true,
  camera: CAMERA_PROFILES[0]!.id,
  lens: LENS_PROFILES[0]!.id,
  focalLength: 85,
  aperture: 1.4,
};

describe('applyCameraPrompt', () => {
  it('leaves the prompt untouched while the panel is off', () => {
    expect(applyCameraPrompt('一只猫', { ...on, enabled: false })).toBe('一只猫');
    expect(applyCameraPrompt('一只猫', undefined)).toBe('一只猫');
  });

  it('keeps the author prompt first and appends the optical language', () => {
    const result = applyCameraPrompt('一只猫', on);
    expect(result.startsWith('一只猫, ')).toBe(true);
    expect(result).toContain(CAMERA_PROFILES[0]!.profilePrompt);
    expect(result).toContain(LENS_PROFILES[0]!.profilePrompt);
    expect(result).toContain('85mm');
    expect(result).toContain('f/1.4');
  });

  it('carries the guardrail that keeps the camera out of the frame', () => {
    // Naming a body and a lens without this reliably returns a photograph of
    // a camera on a tripod, which is why the guardrail leads the clause list.
    const result = applyCameraPrompt('一只猫', on);
    expect(result).toContain('never things to place in the scene');
    expect(result).toContain('no camera, lens, tripod, rig or crew may appear');
  });

  it('puts the guardrail before the equipment names it qualifies', () => {
    const result = applyCameraPrompt('一只猫', on);
    expect(result.indexOf('never things to place in the scene')).toBeLessThan(
      result.indexOf(CAMERA_PROFILES[0]!.profilePrompt),
    );
  });

  it('works with an empty author prompt', () => {
    expect(applyCameraPrompt('', on).startsWith(',')).toBe(false);
  });

  it('falls back to the first body/lens when the stored id is unknown', () => {
    const result = applyCameraPrompt('x', { ...on, camera: 'gone', lens: 'gone' });
    expect(result).toContain(CAMERA_PROFILES[0]!.profilePrompt);
    expect(result).toContain(LENS_PROFILES[0]!.profilePrompt);
  });
});

describe('focal length and aperture vocabulary', () => {
  it('describes every offered focal length without a gap', () => {
    for (const mm of FOCAL_LENGTHS) {
      expect(describeFocalLength(mm)).toContain(`${mm}mm`);
      expect(FOCAL_LENGTH_META[mm]).toBeDefined();
    }
  });

  it('describes every offered aperture without a gap', () => {
    for (const f of APERTURES) {
      expect(describeAperture(f)).toContain(`f/${f}`);
      expect(APERTURE_META[f]).toBeDefined();
    }
  });

  it('moves from wide-angle to telephoto as the focal length grows', () => {
    expect(describeFocalLength(14)).toContain('ultra-wide');
    expect(describeFocalLength(50)).toContain('standard');
    expect(describeFocalLength(200)).toContain('long-telephoto');
  });

  it('moves from shallow to wide depth of field as the aperture closes', () => {
    expect(describeAperture(1.2)).toContain('extremely shallow');
    expect(describeAperture(16)).toContain('very wide depth of field');
  });

  it('has an open-ended tail band, so an off-catalogue value still renders', () => {
    // The pickers only offer the listed values, but a card persisted before a
    // table change can hold anything. A gap here would render an empty clause.
    expect(describeFocalLength(1000)).toContain('1000mm');
    expect(describeAperture(64)).toContain('f/64');
  });
});

describe('catalogue integrity', () => {
  it('has unique ids, so a stored choice always resolves to one entry', () => {
    const cameraIds = CAMERA_PROFILES.map((p) => p.id);
    const lensIds = LENS_PROFILES.map((p) => p.id);
    expect(new Set(cameraIds).size).toBe(cameraIds.length);
    expect(new Set(lensIds).size).toBe(lensIds.length);
  });

  it('gives every entry the prompt fragment and the labels the UI reads', () => {
    for (const profile of [...CAMERA_PROFILES, ...LENS_PROFILES]) {
      expect(profile.profilePrompt.length).toBeGreaterThan(20);
      expect(profile.zhName).not.toBe('');
      expect(profile.label).not.toBe('');
      expect(profile.useCase).not.toBe('');
    }
  });
});
