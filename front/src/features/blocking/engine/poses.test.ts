import { describe, expect, it } from 'vitest';

import type { CastSample } from '../compiler/tracks';
import { STATIC_POSES, gaitPose, mixPose, poseFor } from './poses';

const sample = (overrides: Partial<CastSample> = {}): CastSample => ({
  position: [0, 0, 0],
  yaw: 0,
  base: 'stand',
  prevBase: 'stand',
  baseBlend: 1,
  gesture: 'none',
  gestureWeight: 0,
  distance: 0,
  speed: 0,
  ...overrides,
});

describe('poses', () => {
  it('swings opposite arm and leg while walking', () => {
    const pose = gaitPose('walk', Math.PI / 2);
    // Left thigh forward (negative x) while the left arm swings back.
    expect(pose.joints.lHip[0]).toBeLessThan(0);
    expect(pose.joints.lShoulder[0]).toBeGreaterThan(0);
    expect(pose.joints.rHip[0]).toBeGreaterThan(0);
  });

  it('drops the hips for sitting and lays the body flat for a fall', () => {
    expect(STATIC_POSES.sit.hipsDrop).toBeGreaterThan(0.4);
    expect(STATIC_POSES.fall.bodyPitch).toBe(-90);
  });

  it('blends base actions and layers gestures over the arms only', () => {
    const halfway = poseFor(sample({ base: 'sit', prevBase: 'stand', baseBlend: 0.5 }), 0);
    expect(halfway.hipsDrop).toBeCloseTo(STATIC_POSES.sit.hipsDrop / 2);

    const seatedTalk = poseFor(sample({ base: 'sit', gesture: 'point', gestureWeight: 1 }), 0);
    expect(seatedTalk.joints.lKnee).toEqual(STATIC_POSES.sit.joints.lKnee);
    expect(seatedTalk.joints.rShoulder[0]).toBe(-85);
  });

  it('mixes poses linearly', () => {
    const mid = mixPose(STATIC_POSES.stand, STATIC_POSES.kneel, 0.5);
    expect(mid.hipsDrop).toBeCloseTo(STATIC_POSES.kneel.hipsDrop / 2);
  });
});
