import type {
  BlockingBeat,
  BlockingFacing,
  BlockingMark,
  BlockingStartEntry,
  CastAction,
  Vec3,
} from '../types';
import { angleDelta, clamp, lerp, lerpVec, smoothstep, sub, yawTowards } from './math';

/**
 * One cast member's motion through one segment, compiled from the
 * segment's `start` entry and `beats`. Everything is a pure function of
 * local segment time, so the live player and the offscreen exporter sample
 * the exact same values.
 *
 * Actions split into two layers the mannequin blends independently:
 * a *base* (what the legs/body are doing — stand, sit, walk…) that persists
 * until something changes it, and a *gesture* (talk, point, wave…) that is
 * layered over the arms/head for the duration of its beat only.
 */

export type BaseAction = 'stand' | 'sit' | 'kneel' | 'fall' | 'walk' | 'run' | 'pickup';
export type Gesture = 'none' | 'talk' | 'point' | 'wave' | 'hug' | 'fight';

const PERSISTENT_BASES = new Set<CastAction>(['stand', 'sit', 'kneel', 'fall']);
const GESTURES = new Set<CastAction>(['talk', 'point', 'wave', 'hug', 'fight']);

export const BASE_BLEND_SECONDS = 0.35;
export const GESTURE_FADE_SECONDS = 0.25;
const TRAVEL_TURN_SECONDS = 0.3;
const FACE_TURN_SECONDS = 0.6;
const MIN_TRAVEL_METERS = 0.05;

interface Move {
  t0: number;
  t1: number;
  from: Vec3;
  to: Vec3;
  distanceBefore: number;
  length: number;
}

interface BaseEvent {
  t: number;
  base: BaseAction;
}

interface GestureSpan {
  t0: number;
  t1: number;
  gesture: Exclude<Gesture, 'none'>;
}

type YawState =
  { kind: 'fixed'; deg: number } | { kind: 'target'; target: string; fallback: number };

interface YawEvent {
  t: number;
  state: YawState;
  blend: number;
}

export interface CastSample {
  position: Vec3;
  yaw: number;
  base: BaseAction;
  prevBase: BaseAction;
  /** 0 → fully `prevBase`, 1 → fully `base`. */
  baseBlend: number;
  gesture: Gesture;
  gestureWeight: number;
  /** Metres travelled since the segment started — drives the gait cycle. */
  distance: number;
  speed: number;
}

/** Resolves a facing target (a cast id, an anchor id, or `camera`) to a
 * world position at local time `t`, or `null` when it cannot. */
export type TargetResolver = (target: string, t: number) => Vec3 | null;

export const markPosition = (mark: BlockingMark): Vec3 => [mark.x, 0, mark.z];

function moveProgress(u: number): number {
  // Half linear, half smoothstep: walkers accelerate and settle, but do not
  // crawl through the middle of the move the way pure smoothstep would.
  const x = clamp(u, 0, 1);
  return lerp(x, smoothstep(x), 0.5);
}

function facingState(face: BlockingFacing | null | undefined, fallback: number): YawState {
  if (!face) return { kind: 'fixed', deg: fallback };
  if (face.target) return { kind: 'target', target: face.target, fallback: face.deg ?? fallback };
  return { kind: 'fixed', deg: face.deg ?? 0 };
}

export class CastTrack {
  readonly id: string;
  private readonly origin: Vec3;
  private readonly moves: Move[] = [];
  private readonly baseEvents: BaseEvent[] = [];
  private readonly gestures: GestureSpan[] = [];
  private readonly yawEvents: YawEvent[] = [];

  constructor(start: BlockingStartEntry, beats: BlockingBeat[]) {
    this.id = start.cast_id;
    this.origin = markPosition(start.at);

    const startBase: BaseAction = PERSISTENT_BASES.has(start.action)
      ? (start.action as BaseAction)
      : start.action === 'pickup'
        ? 'pickup'
        : 'stand';
    this.baseEvents.push({ t: 0, base: startBase });
    this.yawEvents.push({ t: 0, state: facingState(start.face, 0), blend: 0 });

    const mine = beats.filter((beat) => beat.cast_id === this.id).sort((a, b) => a.t0 - b.t0);
    const startGesture = GESTURES.has(start.action) ? start.action : null;
    if (startGesture) {
      this.gestures.push({
        t0: 0,
        t1: mine[0]?.t0 ?? Number.POSITIVE_INFINITY,
        gesture: startGesture as GestureSpan['gesture'],
      });
    }

    let position = this.origin;
    let distance = 0;
    let base = startBase;
    for (const beat of mine) {
      const target = beat.to ? markPosition(beat.to) : null;
      const travel = target ? Math.hypot(target[0] - position[0], target[2] - position[2]) : 0;
      const moving = target !== null && travel > MIN_TRAVEL_METERS;

      if (moving && target) {
        this.moves.push({
          t0: beat.t0,
          t1: beat.t1,
          from: position,
          to: target,
          distanceBefore: distance,
          length: travel,
        });
        const locomotion: BaseAction = beat.action === 'run' ? 'run' : 'walk';
        this.baseEvents.push({ t: beat.t0, base: locomotion });
        const heading = yawTowards(position, target) ?? 0;
        this.yawEvents.push({
          t: beat.t0,
          state: { kind: 'fixed', deg: heading },
          blend: TRAVEL_TURN_SECONDS,
        });
        // Arriving somewhere ends in the persistent pose the beat named
        // (`sit` at the chair), else back to standing.
        base = PERSISTENT_BASES.has(beat.action) ? (beat.action as BaseAction) : 'stand';
        this.baseEvents.push({ t: beat.t1, base });
        if (beat.face) {
          this.yawEvents.push({
            t: beat.t1,
            state: facingState(beat.face, heading),
            blend: FACE_TURN_SECONDS,
          });
        }
        distance += travel;
        position = target;
      } else {
        if (PERSISTENT_BASES.has(beat.action)) {
          base = beat.action as BaseAction;
          this.baseEvents.push({ t: beat.t0, base });
        } else if (beat.action === 'pickup') {
          this.baseEvents.push({ t: beat.t0, base: 'pickup' });
          this.baseEvents.push({ t: beat.t1, base });
        }
        if (GESTURES.has(beat.action)) {
          this.gestures.push({
            t0: beat.t0,
            t1: beat.t1,
            gesture: beat.action as GestureSpan['gesture'],
          });
        }
        if (beat.face) {
          this.yawEvents.push({
            t: beat.t0,
            state: facingState(beat.face, 0),
            blend: Math.min(FACE_TURN_SECONDS, Math.max(0.1, beat.t1 - beat.t0)),
          });
        }
      }
    }
    this.baseEvents.sort((a, b) => a.t - b.t);
    this.yawEvents.sort((a, b) => a.t - b.t);
  }

  position(t: number): Vec3 {
    let position = this.origin;
    for (const move of this.moves) {
      if (t < move.t0) return position;
      if (t <= move.t1) {
        const u = move.t1 > move.t0 ? (t - move.t0) / (move.t1 - move.t0) : 1;
        return lerpVec(move.from, move.to, moveProgress(u));
      }
      position = move.to;
    }
    return position;
  }

  private travel(t: number): { distance: number; speed: number } {
    let distance = 0;
    for (const move of this.moves) {
      if (t < move.t0) break;
      const span = Math.max(move.t1 - move.t0, 1e-3);
      if (t <= move.t1) {
        const u = (t - move.t0) / span;
        const eased = moveProgress(u);
        // Derivative of the eased progress, so the stride slows as the
        // walker settles instead of feet sliding at full cadence.
        const h = 1e-3;
        const rate = (moveProgress(u + h) - moveProgress(u - h)) / (2 * h);
        return {
          distance: move.distanceBefore + move.length * eased,
          speed: (move.length * rate) / span,
        };
      }
      distance = move.distanceBefore + move.length;
    }
    return { distance, speed: 0 };
  }

  private baseAt(t: number): { base: BaseAction; prev: BaseAction; blend: number } {
    let index = 0;
    for (let i = 0; i < this.baseEvents.length; i += 1) {
      if (this.baseEvents[i]!.t <= t) index = i;
    }
    const current = this.baseEvents[index]!;
    const prev = this.baseEvents[index - 1] ?? current;
    const blend = index === 0 ? 1 : smoothstep((t - current.t) / BASE_BLEND_SECONDS);
    return { base: current.base, prev: prev.base, blend };
  }

  private gestureAt(t: number): { gesture: Gesture; weight: number } {
    for (const span of this.gestures) {
      if (t < span.t0 || t > span.t1) continue;
      const fadeIn = span.t0 <= 0 ? 1 : smoothstep((t - span.t0) / GESTURE_FADE_SECONDS);
      const fadeOut = Number.isFinite(span.t1)
        ? smoothstep((span.t1 - t) / GESTURE_FADE_SECONDS)
        : 1;
      return { gesture: span.gesture, weight: Math.min(fadeIn, fadeOut) };
    }
    return { gesture: 'none', weight: 0 };
  }

  private yawOf(state: YawState, t: number, at: Vec3, resolve: TargetResolver): number {
    if (state.kind === 'fixed') return state.deg;
    const target = resolve(state.target, t);
    if (!target) return state.fallback;
    return yawTowards(at, target) ?? state.fallback;
  }

  yaw(t: number, resolve: TargetResolver): number {
    const at = this.position(t);
    let index = 0;
    for (let i = 0; i < this.yawEvents.length; i += 1) {
      if (this.yawEvents[i]!.t <= t) index = i;
    }
    const current = this.yawEvents[index]!;
    const desired = this.yawOf(current.state, t, at, resolve);
    if (index === 0 || current.blend <= 0) return desired;
    const u = (t - current.t) / current.blend;
    if (u >= 1) return desired;
    // Blend from wherever the previous state had the body pointing *at the
    // switch*, so a turn starts from the pose that was actually on screen.
    const before = this.yaw(current.t - 1e-4, resolve);
    return before + angleDelta(before, desired) * smoothstep(u);
  }

  sample(t: number, resolve: TargetResolver): CastSample {
    const { base, prev, blend } = this.baseAt(t);
    const { gesture, weight } = this.gestureAt(t);
    const { distance, speed } = this.travel(t);
    return {
      position: this.position(t),
      yaw: this.yaw(t, resolve),
      base,
      prevBase: prev,
      baseBlend: blend,
      gesture,
      gestureWeight: weight,
      distance,
      speed,
    };
  }

  /** Where the cast member ends the segment — the next segment in the same
   * set starts from its own `start`, but tools (e.g. the picker's preview)
   * want this. */
  endPosition(): Vec3 {
    return this.moves.at(-1)?.to ?? this.origin;
  }
}

export const planarDistance = (a: Vec3, b: Vec3) => {
  const d = sub(a, b);
  return Math.hypot(d[0], d[2]);
};
