import type { BaseAction, CastSample, Gesture } from '../compiler/tracks';
import { clamp, lerp } from '../compiler/math';

/**
 * Procedural poses for the FK mannequin — joint rotation tables plus a
 * sine-driven gait, instead of skinned animation clips: nothing to load or
 * license, every action is a few numbers the tests can pin, and the blend
 * between any two actions is a plain per-joint lerp.
 *
 * Angles are raw Euler degrees applied to each joint group, in the
 * mannequin's own conventions (see `mannequin.ts`): limbs hang along -y, so
 * a *negative* x swings an arm or thigh forward, a positive x bends a knee
 * back, a negative x bends an elbow forward; the spine chain points +y, so
 * a positive x leans it forward. Arm z is abduction (+ for left, − for right).
 */

export const JOINTS = [
  'spine',
  'chest',
  'neck',
  'head',
  'lShoulder',
  'rShoulder',
  'lElbow',
  'rElbow',
  'lHip',
  'rHip',
  'lKnee',
  'rKnee',
] as const;
export type JointName = (typeof JOINTS)[number];
export type Euler3 = [number, number, number];

export interface Pose {
  /** How far the hips sit below standing height, metres at 1.7m tall. */
  hipsDrop: number;
  /** Whole-body pitch about the hips, degrees (−90 = lying face up). */
  bodyPitch: number;
  joints: Record<JointName, Euler3>;
}

const zero = (): Euler3 => [0, 0, 0];

function pose(partial: Partial<Record<JointName, Euler3>>, extra: Partial<Pose> = {}): Pose {
  const joints = Object.fromEntries(JOINTS.map((name) => [name, partial[name] ?? zero()])) as Record<
    JointName,
    Euler3
  >;
  return { hipsDrop: 0, bodyPitch: 0, ...extra, joints };
}

const RELAXED_ARMS: Partial<Record<JointName, Euler3>> = {
  lShoulder: [0, 0, 6],
  rShoulder: [0, 0, -6],
  lElbow: [-8, 0, 0],
  rElbow: [-8, 0, 0],
};

export const STATIC_POSES: Record<Exclude<BaseAction, 'walk' | 'run'>, Pose> = {
  stand: pose(RELAXED_ARMS),
  sit: pose(
    {
      spine: [4, 0, 0],
      lShoulder: [-25, 0, 8],
      rShoulder: [-25, 0, -8],
      lElbow: [-45, 0, 0],
      rElbow: [-45, 0, 0],
      lHip: [-88, 0, 4],
      rHip: [-88, 0, -4],
      lKnee: [88, 0, 0],
      rKnee: [88, 0, 0],
    },
    { hipsDrop: 0.47 },
  ),
  kneel: pose(
    {
      ...RELAXED_ARMS,
      spine: [6, 0, 0],
      lHip: [-88, 0, 2],
      lKnee: [88, 0, 0],
      rHip: [-4, 0, -2],
      rKnee: [96, 0, 0],
    },
    { hipsDrop: 0.36 },
  ),
  fall: pose(
    {
      lShoulder: [0, 0, 40],
      rShoulder: [0, 0, -40],
      lElbow: [-20, 0, 0],
      rElbow: [-20, 0, 0],
      lHip: [0, 0, 8],
      rHip: [0, 0, -8],
      lKnee: [10, 0, 0],
      rKnee: [10, 0, 0],
    },
    { hipsDrop: 0.8, bodyPitch: -90 },
  ),
  pickup: pose(
    {
      spine: [45, 0, 0],
      chest: [15, 0, 0],
      neck: [-15, 0, 0],
      lShoulder: [-75, 0, 8],
      rShoulder: [-75, 0, -8],
      lElbow: [-10, 0, 0],
      rElbow: [-10, 0, 0],
      lHip: [-55, 0, 4],
      rHip: [-55, 0, -4],
      lKnee: [85, 0, 0],
      rKnee: [85, 0, 0],
    },
    { hipsDrop: 0.25 },
  ),
};

/** Metres covered by one full gait cycle (two steps) at 1.7m tall. */
export const STRIDE_METERS: Record<'walk' | 'run', number> = { walk: 1.4, run: 2.4 };

export function gaitPose(kind: 'walk' | 'run', phase: number): Pose {
  const s = Math.sin(phase);
  // A knee folds while its thigh swings forward (hip angle decreasing).
  const lift = (offset: number) => Math.max(0, Math.cos(phase + offset));
  if (kind === 'walk') {
    return pose(
      {
        spine: [3, 0, 0],
        lShoulder: [18 * s, 0, 6],
        rShoulder: [-18 * s, 0, -6],
        lElbow: [-15, 0, 0],
        rElbow: [-15, 0, 0],
        lHip: [-24 * s, 0, 0],
        rHip: [24 * s, 0, 0],
        lKnee: [8 + 32 * lift(0), 0, 0],
        rKnee: [8 + 32 * lift(Math.PI), 0, 0],
      },
      { hipsDrop: 0.02 * Math.abs(Math.cos(phase)) },
    );
  }
  return pose(
    {
      spine: [12, 0, 0],
      lShoulder: [35 * s, 0, 8],
      rShoulder: [-35 * s, 0, -8],
      lElbow: [-85, 0, 0],
      rElbow: [-85, 0, 0],
      lHip: [-40 * s, 0, 0],
      rHip: [40 * s, 0, 0],
      lKnee: [20 + 70 * lift(0), 0, 0],
      rKnee: [20 + 70 * lift(Math.PI), 0, 0],
    },
    { hipsDrop: 0.05 * Math.abs(Math.cos(phase)) },
  );
}

/** Gestures only drive the joints they name; everything else keeps the
 * base pose underneath (so a seated character can talk). */
export function gestureJoints(
  gesture: Exclude<Gesture, 'none'>,
  clock: number,
): Partial<Record<JointName, Euler3>> {
  const osc = (hz: number, offset = 0) => Math.sin(clock * 2 * Math.PI * hz + offset);
  switch (gesture) {
    case 'talk':
      return {
        rShoulder: [-(25 + 10 * osc(1.4)), 0, -10],
        rElbow: [-(70 + 15 * osc(1.4, 1)), 0, 0],
        lShoulder: [-(10 + 5 * osc(0.9, 2)), 0, 8],
        lElbow: [-35, 0, 0],
        head: [3 * osc(0.8), 4 * osc(0.5), 0],
      };
    case 'point':
      return { rShoulder: [-85, 0, -8], rElbow: [-4, 0, 0], head: [0, 0, 0] };
    case 'wave':
      return { rShoulder: [0, 0, -150], rElbow: [-(25 + 25 * osc(2)), 0, 0] };
    case 'hug':
      return {
        spine: [8, 0, 0],
        lShoulder: [-80, 0, 18],
        rShoulder: [-80, 0, -18],
        lElbow: [-70, 0, 0],
        rElbow: [-70, 0, 0],
      };
    case 'fight': {
      const right = Math.max(0, osc(1.5));
      const left = Math.max(0, osc(1.5, Math.PI));
      return {
        spine: [10, 0, 0],
        rShoulder: [-(40 + 50 * right), 0, -5],
        rElbow: [-(90 - 80 * right), 0, 0],
        lShoulder: [-(40 + 50 * left), 0, 5],
        lElbow: [-(90 - 80 * left), 0, 0],
      };
    }
  }
}

function mixEuler(a: Euler3, b: Euler3, w: number): Euler3 {
  return [lerp(a[0], b[0], w), lerp(a[1], b[1], w), lerp(a[2], b[2], w)];
}

export function mixPose(a: Pose, b: Pose, w: number): Pose {
  const u = clamp(w, 0, 1);
  const joints = Object.fromEntries(
    JOINTS.map((name) => [name, mixEuler(a.joints[name], b.joints[name], u)]),
  ) as Record<JointName, Euler3>;
  return {
    hipsDrop: lerp(a.hipsDrop, b.hipsDrop, u),
    bodyPitch: lerp(a.bodyPitch, b.bodyPitch, u),
    joints,
  };
}

function basePose(base: BaseAction, sample: CastSample, heightScale: number): Pose {
  if (base === 'walk' || base === 'run') {
    const stride = STRIDE_METERS[base] * heightScale;
    return gaitPose(base, (sample.distance / stride) * 2 * Math.PI);
  }
  return STATIC_POSES[base];
}

/** The mannequin's pose for one sampled frame: blended base, then the
 * gesture layered over the joints it names. `clock` drives gesture
 * oscillation and is the segment's local time, so exports are repeatable. */
export function poseFor(sample: CastSample, clock: number, heightScale = 1): Pose {
  const current = basePose(sample.base, sample, heightScale);
  let result =
    sample.baseBlend >= 1
      ? current
      : mixPose(basePose(sample.prevBase, sample, heightScale), current, sample.baseBlend);
  if (sample.gesture !== 'none' && sample.gestureWeight > 0) {
    const layer = gestureJoints(sample.gesture, clock);
    const joints = { ...result.joints };
    for (const [name, value] of Object.entries(layer) as [JointName, Euler3][]) {
      joints[name] = mixEuler(joints[name], value, sample.gestureWeight);
    }
    result = { ...result, joints };
  }
  return result;
}
