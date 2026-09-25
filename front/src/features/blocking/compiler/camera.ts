import type {
  AspectRatio,
  BlockingCameraOverride,
  BlockingShot,
  CameraHeight,
  CameraPose,
  ShotSize,
  Vec3,
} from '../types';
import {
  DEG,
  add,
  clamp,
  cross,
  forward,
  hashString,
  lerpVec,
  mulberry32,
  normalize,
  rotateAxis,
  rotateY,
  scale,
  smoothstep,
  sub,
} from './math';

/**
 * Shot grammar → camera pose. `frameShot` places the camera for a shot's
 * first frame from film conventions (shot size sets how much of a person is
 * in frame, the lens sets the field of view, and the two together give the
 * distance); `sampleShot` then plays the move preset over the segment.
 */

/** Sensor height along the *vertical* axis of the delivered frame: a
 * full-frame 36×24mm sensor, turned upright for vertical video. */
const SENSOR_VERTICAL_MM: Record<AspectRatio, number> = { '16:9': 24, '1:1': 24, '9:16': 36 };
export const ASPECT_WIDTH_OVER_HEIGHT: Record<AspectRatio, number> = {
  '16:9': 16 / 9,
  '1:1': 1,
  '9:16': 9 / 16,
};

export function fovFromLens(lensMm: number, aspect: AspectRatio): number {
  return (2 * Math.atan(SENSOR_VERTICAL_MM[aspect] / (2 * lensMm))) / DEG;
}

/** Vertical metres in frame, as a function of the subject's height. */
const FRAME_HEIGHT: Record<ShotSize, (height: number) => number> = {
  extreme_wide: () => 16,
  wide: () => 6.5,
  full: (h) => h * 1.3,
  medium: (h) => h * 0.62,
  medium_close: (h) => h * 0.42,
  close: (h) => h * 0.24,
  extreme_close: (h) => h * 0.11,
};

/** Where on the subject the lens aims, as a fraction of their height. */
const AIM_HEIGHT: Record<ShotSize, number> = {
  extreme_wide: 0.5,
  wide: 0.5,
  full: 0.52,
  medium: 0.72,
  medium_close: 0.82,
  close: 0.9,
  extreme_close: 0.93,
};

const ELEVATION_DEG: Record<CameraHeight, number> = {
  ground: -6,
  low: -22,
  eye: 0,
  high: 28,
  overhead: 82,
};

const OTS_BEHIND_METERS: Record<ShotSize, number> = {
  extreme_wide: 2.4,
  wide: 2.0,
  full: 1.7,
  medium: 1.45,
  medium_close: 1.3,
  close: 1.1,
  extreme_close: 1.0,
};
const OTS_SIDE_METERS = 0.58;

const UP: Vec3 = [0, 1, 0];
const MIN_CAMERA_Y = 0.12;

export interface ShotSubject {
  /** Ground position at local time `t`. */
  position: (t: number) => Vec3;
  height: number;
  /** Facing at the start of the segment, degrees. */
  yaw: number;
}

export interface ShotContext {
  aspect: AspectRatio;
  subject: ShotSubject;
  /** The foreground shoulder for an over-the-shoulder shot. */
  over: ShotSubject | null;
  /** Ground-plane spread of everyone on set, so a subject-less group shot
   * widens to hold them all. */
  groupWidth: number;
  seedKey: string;
}

function sideYaw(shot: BlockingShot, subjectYaw: number): number {
  switch (shot.side) {
    case 'left':
      return subjectYaw + 90;
    case 'right':
      return subjectYaw - 90;
    case 'back':
      return subjectYaw + 180;
    default:
      return subjectYaw;
  }
}

export function frameShot(shot: BlockingShot, ctx: ShotContext): CameraPose {
  const fov = fovFromLens(shot.lens_mm, ctx.aspect);
  const subject = ctx.subject;
  const ground = subject.position(0);
  const target: Vec3 = [ground[0], subject.height * AIM_HEIGHT[shot.size], ground[2]];

  if ((shot.side === 'ots_left' || shot.side === 'ots_right') && ctx.over) {
    // Far enough behind the foreground shoulder that it frames one edge of
    // the shot instead of filling it; tighter sizes creep in a little.
    const overAt = ctx.over.position(0);
    const toSubject = normalize([ground[0] - overAt[0], 0, ground[2] - overAt[2]]);
    const shoulderSide = rotateY(toSubject, (shot.side === 'ots_left' ? 90 : -90) * DEG);
    const behind = OTS_BEHIND_METERS[shot.size];
    const position = add(
      add(overAt, scale(toSubject, -behind)),
      add(scale(shoulderSide, OTS_SIDE_METERS), [0, ctx.over.height * 0.87, 0]),
    );
    return { position, target: [ground[0], subject.height * 0.88, ground[2]], fov };
  }

  let frameHeight = FRAME_HEIGHT[shot.size](subject.height);
  const aspect = ASPECT_WIDTH_OVER_HEIGHT[ctx.aspect];
  if (ctx.groupWidth > 0) frameHeight = Math.max(frameHeight, (ctx.groupWidth + 0.8) / aspect);
  const distance = frameHeight / 2 / Math.tan((fov * DEG) / 2);

  const elevation = ELEVATION_DEG[shot.height] * DEG;
  const horizontal = forward(sideYaw(shot, subject.yaw));
  const offset = add(
    scale(horizontal, distance * Math.cos(elevation)),
    scale(UP, distance * Math.sin(elevation)),
  );
  const position = add(target, offset);
  if (shot.height === 'ground') position[1] = Math.max(0.25, MIN_CAMERA_Y);
  position[1] = Math.max(position[1], MIN_CAMERA_Y);
  return { position, target, fov };
}

/** Right-hand vector of a camera (screen +x), on the ground plane. */
function cameraRight(pose: CameraPose): Vec3 {
  const look = normalize(sub(pose.target, pose.position));
  const right = cross(look, UP);
  return Math.hypot(right[0], right[2]) > 1e-6 ? normalize(right) : [1, 0, 0];
}

function handheld(pose: CameraPose, t: number, intensity: number, seedKey: string): CameraPose {
  const random = mulberry32(hashString(seedKey));
  const phases = Array.from({ length: 6 }, () => random() * Math.PI * 2);
  const wave = (i: number) =>
    Math.sin(t * 2 * Math.PI * 0.7 + phases[i]!) * 0.6 +
    Math.sin(t * 2 * Math.PI * 1.7 + phases[i + 3]!) * 0.4;
  const amplitude = 0.015 + 0.05 * intensity;
  const right = cameraRight(pose);
  const jitter = add(scale(right, wave(0) * amplitude), scale(UP, wave(1) * amplitude * 0.7));
  const aimJitter = add(scale(right, wave(2) * amplitude * 1.5), scale(UP, wave(1) * amplitude));
  return {
    position: add(pose.position, jitter),
    target: add(pose.target, aimJitter),
    fov: pose.fov,
  };
}

/**
 * The shot's pose at local time `t` (`u` = t / duration). Moves that sweep
 * (pan, tilt, truck, orbit, crane) are centred on the framed pose, so the
 * subject is framed as planned at the middle of the move rather than drifting
 * out of frame by its end.
 */
export function sampleShot(
  shot: BlockingShot,
  base: CameraPose,
  ctx: ShotContext,
  t: number,
  duration: number,
): CameraPose {
  const move = shot.move;
  const k = clamp(move.intensity, 0, 1);
  const raw = duration > 0 ? clamp(t / duration, 0, 1) : 0;
  const u = move.ease === 'in_out' ? smoothstep(raw) : raw;
  const centred = u - 0.5;
  const look = sub(base.target, base.position);

  switch (move.preset) {
    case 'static':
      return base;
    case 'push_in':
    case 'pull_out': {
      const end = move.preset === 'push_in' ? 1 - 0.45 * k : 1 + 0.8 * k;
      const factor = 1 + (end - 1) * u;
      return { ...base, position: sub(base.target, scale(look, factor)) };
    }
    case 'pan_left':
    case 'pan_right': {
      const sweep = (10 + 35 * k) * DEG * (move.preset === 'pan_left' ? 1 : -1);
      return { ...base, target: add(base.position, rotateY(look, sweep * centred)) };
    }
    case 'tilt_up':
    case 'tilt_down': {
      const sweep = (8 + 25 * k) * DEG * (move.preset === 'tilt_up' ? 1 : -1);
      const axis = cameraRight(base);
      return { ...base, target: add(base.position, rotateAxis(look, axis, sweep * centred)) };
    }
    case 'truck_left':
    case 'truck_right': {
      const travel = (0.5 + 2.5 * k) * (move.preset === 'truck_right' ? 1 : -1);
      const shift = scale(cameraRight(base), travel * centred);
      return { ...base, position: add(base.position, shift), target: add(base.target, shift) };
    }
    case 'orbit_cw':
    case 'orbit_ccw': {
      const sweep = (20 + 70 * k) * DEG * (move.preset === 'orbit_ccw' ? 1 : -1);
      const arm = sub(base.position, base.target);
      return { ...base, position: add(base.target, rotateY(arm, sweep * centred)) };
    }
    case 'crane_up':
    case 'crane_down': {
      const rise = (0.6 + 2.4 * k) * (move.preset === 'crane_up' ? 1 : -1);
      const lift = rise * centred;
      const position = add(base.position, [0, lift, 0]);
      position[1] = Math.max(position[1], MIN_CAMERA_Y);
      return { ...base, position, target: add(base.target, [0, lift * 0.3, 0]) };
    }
    case 'follow': {
      const start = ctx.subject.position(0);
      const now = ctx.subject.position(t);
      const delta = sub(now, start);
      return { ...base, position: add(base.position, delta), target: add(base.target, delta) };
    }
    case 'handheld':
      return handheld(base, t, k, ctx.seedKey);
  }
}

/** A manual camera from the drag editor replaces the shot grammar outright. */
export function sampleOverride(
  override: BlockingCameraOverride,
  t: number,
  duration: number,
): CameraPose {
  const start = override.start;
  const end = override.end ?? override.start;
  const u = smoothstep(duration > 0 ? t / duration : 0);
  return {
    position: lerpVec(start.position as Vec3, end.position as Vec3, u),
    target: lerpVec(start.target as Vec3, end.target as Vec3, u),
    fov: start.fov + (end.fov - start.fov) * u,
  };
}

/**
 * Backs a camera away from its target until every point is inside the
 * frame (with a margin). Used for subject-less group shots, where the
 * centroid framing alone can clip someone standing nearer the lens.
 */
export function fitPointsInFrame(
  pose: CameraPose,
  points: Vec3[],
  aspect: AspectRatio,
  margin = 0.88,
): CameraPose {
  if (points.length === 0) return pose;
  const tanV = Math.tan((pose.fov * DEG) / 2) * margin;
  const tanH = tanV * ASPECT_WIDTH_OVER_HEIGHT[aspect];
  const inside = (position: Vec3) => {
    const f = normalize(sub(pose.target, position));
    const r = normalize(cross(f, UP));
    const u = cross(r, f);
    return points.every((point) => {
      const v = sub(point, position);
      const depth = v[0] * f[0] + v[1] * f[1] + v[2] * f[2];
      if (depth <= 0.1) return false;
      const x = v[0] * r[0] + v[1] * r[1] + v[2] * r[2];
      const y = v[0] * u[0] + v[1] * u[1] + v[2] * u[2];
      return Math.abs(x) / depth <= tanH && Math.abs(y) / depth <= tanV;
    });
  };
  let position = pose.position;
  const arm = sub(pose.position, pose.target);
  for (let step = 1; step <= 30 && !inside(position); step += 1) {
    position = add(pose.target, scale(arm, 1 + step * 0.1));
  }
  return { ...pose, position };
}
