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
import { lineOfSightClear, pointInsideSolid, type Obstacle } from './obstacles';

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

export interface FrameRect {
  x: number;
  y: number;
  width: number;
  height: number;
}

/**
 * Where the delivered frame sits inside a viewport of `width`×`height`:
 * the largest rect of the document's aspect that fits, less a small margin
 * so the matte around it stays visible. The viewport renders the director
 * camera across the *whole* canvas (a wider field of view) and dims what
 * falls outside this rect, so the author sees the frame at full size plus
 * what is just off it — the exporter renders exactly the rect.
 */
export function frameRectFor(
  width: number,
  height: number,
  aspect: AspectRatio,
  margin = 0.92,
): FrameRect {
  const ratio = ASPECT_WIDTH_OVER_HEIGHT[aspect];
  const fitted =
    width / height > ratio ? { width: height * ratio, height } : { width, height: width / ratio };
  const frameWidth = fitted.width * margin;
  const frameHeight = fitted.height * margin;
  return {
    x: (width - frameWidth) / 2,
    y: (height - frameHeight) / 2,
    width: frameWidth,
    height: frameHeight,
  };
}

/** The vertical field of view that shows the frame's `fov` inside
 * `frameHeight` pixels of a `viewportHeight`-pixel canvas. */
export function widenedFov(fov: number, frameHeight: number, viewportHeight: number): number {
  if (frameHeight <= 0 || viewportHeight <= frameHeight) return fov;
  const half = Math.tan((fov * DEG) / 2) * (viewportHeight / frameHeight);
  return (2 * Math.atan(half)) / DEG;
}

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
  /** Ground position at segment-local time `t`. */
  position: (t: number) => Vec3;
  height: number;
  /** Facing at the start of the shot, degrees. */
  yaw: number;
  /** A person who moves: the lens follows them (pan/tilt, or a full follow).
   * False for an anchor or a group centroid. */
  tracked?: boolean;
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
  /** Segment-local time this shot starts at; `sampleShot`'s `t` is
   * relative to it. */
  start?: number;
  /** Solid set geometry the lens must see past. */
  obstacles?: Obstacle[];
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
  const start = ctx.start ?? 0;
  const ground = subject.position(start);
  const target: Vec3 = [ground[0], subject.height * AIM_HEIGHT[shot.size], ground[2]];

  if ((shot.side === 'ots_left' || shot.side === 'ots_right') && ctx.over) {
    // Far enough behind the foreground shoulder that it frames one edge of
    // the shot instead of filling it; tighter sizes creep in a little.
    const overAt = ctx.over.position(start);
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

/** Where the lens aims on the subject at segment time `t`, averaged over a
 * short window so a walk's bob and a turn do not jitter the frame. */
export function subjectAim(ctx: ShotContext, aimHeight: number, t: number, window = 0.4): Vec3 {
  const samples = [-1, -0.5, 0, 0.5, 1].map((k) => ctx.subject.position(t + k * window));
  const x = samples.reduce((sum, p) => sum + p[0], 0) / samples.length;
  const z = samples.reduce((sum, p) => sum + p[2], 0) / samples.length;
  return [x, aimHeight, z];
}

/**
 * Backs the camera away along its arm until every point is at least
 * `minDepth` in front of it — so a subject who walks during a static or
 * panning shot never passes beside or behind the lens. The lens pans to
 * keep them framed (`sampleShot`); this keeps that pan possible.
 */
export function keepAhead(pose: CameraPose, points: Vec3[], minDepth = 1.4): CameraPose {
  if (points.length === 0) return pose;
  const arm = sub(pose.position, pose.target);
  const reach = Math.hypot(arm[0], arm[1], arm[2]);
  if (reach < 1e-6) return pose;
  const direction = scale(arm, 1 / reach);
  // Depth of a point along the camera's (horizontal) view axis.
  const depthAt = (position: Vec3, point: Vec3) => {
    const v = sub(point, position);
    return -(v[0] * direction[0] + v[2] * direction[2]);
  };
  let position = pose.position;
  for (let step = 1; step <= 40; step += 1) {
    if (points.every((point) => depthAt(position, point) >= minDepth)) break;
    position = add(pose.target, scale(arm, 1 + step * 0.1));
  }
  return { ...pose, position };
}

/**
 * Moves a camera that cannot see its subject — a wall or a prop in the way,
 * or the lens sitting inside something — to the nearest pose that can:
 * swing around the subject first, then come closer. `times` are the
 * segment-local moments the view must be clear at (start, middle, end).
 */
export function avoidOcclusion(
  pose: CameraPose,
  ctx: ShotContext,
  aimAt: (t: number) => Vec3,
  times: number[],
): CameraPose {
  const obstacles = ctx.obstacles ?? [];
  if (obstacles.length === 0) return pose;
  const score = (position: Vec3) =>
    pointInsideSolid(obstacles, position)
      ? -1
      : times.filter((t) => lineOfSightClear(obstacles, position, aimAt(t))).length;
  const full = times.length;
  let best = pose;
  let bestScore = score(pose.position);
  if (bestScore === full) return pose;
  const arm = sub(pose.position, pose.target);
  for (const reach of [1, 0.8, 0.62, 0.48]) {
    for (const degrees of [0, 25, -25, 50, -50, 80, -80, 115, -115, 150, -150, 180]) {
      if (reach === 1 && degrees === 0) continue;
      const position = add(pose.target, rotateY(scale(arm, reach), degrees * DEG));
      position[1] = Math.max(position[1], MIN_CAMERA_Y);
      const candidate = score(position);
      if (candidate > bestScore) {
        best = { ...pose, position };
        bestScore = candidate;
        if (candidate === full) return best;
      }
    }
  }
  return best;
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
  const moved = applyMove(shot, base, ctx, t, duration);
  if (moveTracks(shot) && ctx.subject.tracked) {
    // Keep a moving subject in frame: the lens pans/tilts with them while
    // the camera body does whatever the preset says.
    const start = ctx.start ?? 0;
    const height = base.target[1];
    const drift = sub(subjectAim(ctx, height, start + t), subjectAim(ctx, height, start));
    return { ...moved, target: add(moved.target, drift) };
  }
  return moved;
}

/** `follow` already carries the whole camera with the subject. */
function moveTracks(shot: BlockingShot): boolean {
  return shot.move.preset !== 'follow';
}

function applyMove(
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
      const origin = ctx.start ?? 0;
      const start = subjectAim(ctx, 0, origin);
      const now = subjectAim(ctx, 0, origin + t);
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
