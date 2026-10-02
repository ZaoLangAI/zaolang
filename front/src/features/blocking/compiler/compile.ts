import type {
  BlockingCastMember,
  BlockingDocument,
  BlockingSegment,
  BlockingSet,
  BlockingShot,
  CameraPose,
  Vec3,
} from '../types';
import {
  avoidOcclusion,
  fitPointsInFrame,
  frameShot,
  keepAhead,
  sampleOverride,
  sampleShot,
  subjectAim,
  type ShotContext,
  type ShotSubject,
} from './camera';
import { lerp, lerpVec, smoothstep } from './math';
import { setObstacles, WalkGrid, type Circle, type Obstacle } from './obstacles';
import { CastTrack, markPosition, type CastSample, type TargetResolver } from './tracks';

/**
 * `compileBlocking(document)` → a `Timeline` that can be sampled at any
 * episode time. This is the only place the semantic document becomes
 * motion; the three.js player and the MP4 exporter are both thin consumers
 * of `Timeline.sample`, which is what guarantees the exported reference
 * video matches what the author watched.
 *
 * The compiler also *repairs* staging a model gets physically wrong, so
 * the result is watchable whichever vendor wrote the document:
 * - marks inside furniture are moved to the nearest free floor, and people
 *   placed on top of each other are spread apart;
 * - walks are routed around furniture and around the other cast;
 * - every shot is framed from where its subject is when that shot starts,
 *   follows a moving subject, and is moved if a wall blocks the view.
 */

export const CAMERA_TARGET = 'camera';
const DEFAULT_HEIGHT = 1.7;
const FIT_SAMPLES = [0, 0.25, 0.5, 0.75, 1];
/** Nobody stands closer than this to anyone else. */
export const PERSONAL_SPACE = 0.8;
/** Last-resort separation when two walkers still meet. */
const MIN_SEPARATION = 0.55;
/** Cast a walker plans around: people standing still, and where they end up. */
const PASSING_RADIUS = 0.55;
const ARRIVAL_RADIUS = 0.75;
/** Longest blend into a `continuous` shot. */
const CONTINUOUS_BLEND_SECONDS = 1;

export interface CompiledShot {
  index: number;
  /** Segment-local start/end. */
  start: number;
  end: number;
  source: BlockingShot;
  base: CameraPose;
  context: ShotContext;
}

export interface CompiledSegment {
  index: number;
  key: string;
  heading: string;
  set: BlockingSet;
  /** Episode time where this segment starts. */
  start: number;
  duration: number;
  source: BlockingSegment;
  tracks: Map<string, CastTrack>;
  shots: CompiledShot[];
  obstacles: Obstacle[];
}

export interface CastFrame extends CastSample {
  id: string;
  member: BlockingCastMember;
}

export interface FrameState {
  time: number;
  segment: CompiledSegment;
  /** Seconds since `segment.start`. */
  localTime: number;
  camera: CameraPose;
  /** The shot on screen at this moment (`null` under a manual camera). */
  shot: CompiledShot | null;
  /** Only the cast on set in this segment. */
  cast: CastFrame[];
}

export interface Timeline {
  duration: number;
  segments: CompiledSegment[];
  cast: BlockingCastMember[];
  aspect: BlockingDocument['aspect_ratio'];
  sample: (time: number) => FrameState | null;
  segmentAt: (time: number) => CompiledSegment | null;
}

function anchorPositions(set: BlockingSet): Map<string, Vec3> {
  return new Map((set.anchors ?? []).map((anchor) => [anchor.id, [anchor.x, 0, anchor.z]]));
}

function makeResolver(
  tracks: Map<string, CastTrack>,
  anchors: Map<string, Vec3>,
  camera: ((t: number) => CameraPose) | null,
): TargetResolver {
  return (target, t) => {
    const track = tracks.get(target);
    if (track) return track.position(t);
    const anchor = anchors.get(target);
    if (anchor) return anchor;
    if (target === CAMERA_TARGET && camera) return camera(t).position;
    return null;
  };
}

/**
 * Start marks, repaired: out of furniture, and at least `PERSONAL_SPACE`
 * apart (pushed along the line between them, a few relaxation passes).
 */
function resolveStarts(segment: BlockingSegment, grid: WalkGrid): Map<string, Vec3> {
  const entries = segment.start ?? [];
  const points = entries.map((entry) => grid.nearestFree(entry.at.x, entry.at.z));
  for (let pass = 0; pass < 6; pass += 1) {
    let moved = false;
    for (let i = 0; i < points.length; i += 1) {
      for (let j = i + 1; j < points.length; j += 1) {
        const a = points[i]!;
        const b = points[j]!;
        let dx = b[0] - a[0];
        let dz = b[1] - a[1];
        let distance = Math.hypot(dx, dz);
        if (distance >= PERSONAL_SPACE - 1e-6) continue;
        if (distance < 1e-6) {
          dx = 1;
          dz = 0;
          distance = 1;
        }
        const push = (PERSONAL_SPACE - Math.min(distance, PERSONAL_SPACE)) / 2;
        const ux = dx / distance;
        const uz = dz / distance;
        points[i] = [a[0] - ux * push, a[1] - uz * push];
        points[j] = [b[0] + ux * push, b[1] + uz * push];
        moved = true;
      }
    }
    if (!moved) break;
  }
  const starts = new Map<string, Vec3>();
  entries.forEach((entry, index) => {
    const [x, z] = grid.nearestFree(points[index]![0], points[index]![1]);
    starts.set(entry.cast_id, [x, 0, z]);
  });
  return starts;
}

function buildTracks(
  segment: BlockingSegment,
  castById: Map<string, BlockingCastMember>,
  grid: WalkGrid,
): Map<string, CastTrack> {
  const entries = (segment.start ?? []).filter((entry) => castById.has(entry.cast_id));
  const beats = segment.beats ?? [];
  const starts = resolveStarts(segment, grid);

  // Pass 1: routes around furniture only.
  const firstPass = new Map<string, CastTrack>();
  for (const entry of entries) {
    firstPass.set(
      entry.cast_id,
      new CastTrack(entry, beats, (from, to) => grid.plan(from, to), starts.get(entry.cast_id)),
    );
  }
  // Pass 2: also around the other cast — where they stand when the walk
  // starts, and where they will be when it ends — so nobody walks through
  // or stops inside somebody else.
  const tracks = new Map<string, CastTrack>();
  for (const entry of entries) {
    const others = [...firstPass.values()].filter((track) => track.id !== entry.cast_id);
    const planner = (from: Vec3, to: Vec3, t0: number, t1: number) => {
      const extra: Circle[] = others.flatMap((track) => {
        const here = track.position(t0);
        const there = track.position(t1);
        return [
          { x: here[0], z: here[2], r: PASSING_RADIUS },
          { x: there[0], z: there[2], r: ARRIVAL_RADIUS },
        ];
      });
      return grid.plan(from, to, extra);
    };
    tracks.set(entry.cast_id, new CastTrack(entry, beats, planner, starts.get(entry.cast_id)));
  }
  return tracks;
}

function compileShots(
  source: BlockingSegment,
  tracks: Map<string, CastTrack>,
  anchors: Map<string, Vec3>,
  castById: Map<string, BlockingCastMember>,
  obstacles: Obstacle[],
  aspect: BlockingDocument['aspect_ratio'],
): CompiledShot[] {
  // Facing the camera counts as facing +z while framing (where a front
  // camera goes anyway); the real camera resolves `camera` facings later.
  const provisional = makeResolver(tracks, anchors, null);
  const heightOf = (castId: string) => castById.get(castId)?.height_m ?? DEFAULT_HEIGHT;
  const onSet = [...tracks.values()];
  const averageHeight = onSet.length
    ? onSet.reduce((sum, track) => sum + heightOf(track.id), 0) / onSet.length
    : DEFAULT_HEIGHT;

  const subjectFor = (ref: string | null | undefined, at: number): ShotSubject | null => {
    if (!ref) return null;
    const track = tracks.get(ref);
    if (track) {
      return {
        position: (t) => track.position(t),
        height: heightOf(ref),
        yaw: track.yaw(at, provisional),
        tracked: true,
      };
    }
    const anchor = anchors.get(ref);
    if (anchor) return { position: () => anchor, height: 1.3, yaw: 0 };
    return null;
  };

  const centroid = (t: number): Vec3 => {
    if (onSet.length === 0) return [0, 0, 0];
    const points = onSet.map((track) => track.position(t));
    return [
      points.reduce((sum, p) => sum + p[0], 0) / points.length,
      0,
      points.reduce((sum, p) => sum + p[2], 0) / points.length,
    ];
  };

  const sources = source.shots ?? [];
  return sources.map((shot, index) => {
    const start = Math.min(Math.max(shot.t0 ?? 0, 0), source.duration_s);
    const end = index + 1 < sources.length ? sources[index + 1]!.t0 : source.duration_s;
    const windowTimes = FIT_SAMPLES.map((u) => start + (end - start) * u);
    const subject = subjectFor(shot.subject, start);
    const xs = onSet.map((track) => track.position(start)[0]);
    const context: ShotContext = {
      aspect,
      subject: subject ?? { position: centroid, height: averageHeight, yaw: 0 },
      over: subjectFor(shot.over, start),
      groupWidth: subject || xs.length < 2 ? 0 : Math.max(...xs) - Math.min(...xs),
      seedKey: `${source.key}#${index}`,
      start,
      obstacles,
    };

    let base = frameShot(shot, context);
    if (!subject) {
      // The group shot holds everyone on set, wherever they walk to during it.
      const groupPoints = onSet.flatMap((track) =>
        windowTimes.flatMap((t) => {
          const at = track.position(t);
          return [at, [at[0], heightOf(track.id) * 1.08, at[2]] as Vec3];
        }),
      );
      base = fitPointsInFrame(base, groupPoints, aspect);
    }
    if (subject?.tracked && shot.move.preset !== 'follow') {
      // A subject who walks during this shot must stay in front of a
      // camera that does not travel with them.
      base = keepAhead(
        base,
        windowTimes.map((t) => subject.position(t)),
      );
    }
    if (shot.side !== 'ots_left' && shot.side !== 'ots_right') {
      const aimHeight = base.target[1];
      base = avoidOcclusion(base, context, (t) => subjectAim(context, aimHeight, t), [
        start,
        (start + end) / 2,
        end,
      ]);
    }
    return { index, start, end, source: shot, base, context };
  });
}

function compileSegment(
  source: BlockingSegment,
  index: number,
  start: number,
  set: BlockingSet,
  castById: Map<string, BlockingCastMember>,
  aspect: BlockingDocument['aspect_ratio'],
): CompiledSegment {
  const obstacles = setObstacles(set);
  const grid = new WalkGrid(set, obstacles);
  const tracks = buildTracks(source, castById, grid);
  const anchors = anchorPositions(set);
  return {
    index,
    key: source.key,
    heading: source.heading,
    set,
    start,
    duration: source.duration_s,
    source,
    tracks,
    shots: compileShots(source, tracks, anchors, castById, obstacles, aspect),
    obstacles,
  };
}

export function shotAt(segment: CompiledSegment, localTime: number): CompiledShot | null {
  let current: CompiledShot | null = segment.shots[0] ?? null;
  for (const shot of segment.shots) if (shot.start <= localTime) current = shot;
  return current;
}

function poseInShot(shot: CompiledShot, localTime: number): CameraPose {
  const length = shot.end - shot.start;
  return sampleShot(
    shot.source,
    shot.base,
    shot.context,
    Math.min(Math.max(localTime - shot.start, 0), length),
    length,
  );
}

export function cameraAt(segment: CompiledSegment, localTime: number): CameraPose {
  const override = segment.source.camera_override;
  if (override) return sampleOverride(override, localTime, segment.duration);
  const shot = shotAt(segment, localTime);
  if (!shot) return { position: [0, 1.6, 6], target: [0, 1.2, 0], fov: 40 };
  const pose = poseInShot(shot, localTime);
  const previous = segment.shots[shot.index - 1];
  if (!previous || shot.source.transition !== 'continuous') return pose;
  // A continuous shot starts from where the previous one ended and glides
  // into its own framing instead of cutting.
  const blend = Math.min(CONTINUOUS_BLEND_SECONDS, (shot.end - shot.start) * 0.4);
  const u = blend > 0 ? (localTime - shot.start) / blend : 1;
  if (u >= 1) return pose;
  const from = poseInShot(previous, previous.end);
  const w = smoothstep(u);
  return {
    position: lerpVec(from.position, pose.position, w),
    target: lerpVec(from.target, pose.target, w),
    fov: lerp(from.fov, pose.fov, w),
  };
}

/** Pushes apart any two people closer than `MIN_SEPARATION` — the backstop
 * for walkers whose routes still cross mid-move. Deterministic: pairs in id
 * order, two passes. */
function separate(cast: CastFrame[]): void {
  const ordered = [...cast].sort((a, b) => (a.id < b.id ? -1 : 1));
  for (let pass = 0; pass < 2; pass += 1) {
    for (let i = 0; i < ordered.length; i += 1) {
      for (let j = i + 1; j < ordered.length; j += 1) {
        const a = ordered[i]!;
        const b = ordered[j]!;
        if (a.base === 'fall' || b.base === 'fall') continue;
        let dx = b.position[0] - a.position[0];
        let dz = b.position[2] - a.position[2];
        let distance = Math.hypot(dx, dz);
        if (distance >= MIN_SEPARATION) continue;
        if (distance < 1e-6) {
          dx = 1;
          dz = 0;
          distance = 1;
        }
        const push = (MIN_SEPARATION - Math.min(distance, MIN_SEPARATION)) / 2;
        const ux = dx / distance;
        const uz = dz / distance;
        a.position = [a.position[0] - ux * push, 0, a.position[2] - uz * push];
        b.position = [b.position[0] + ux * push, 0, b.position[2] + uz * push];
      }
    }
  }
}

export function sampleSegment(
  segment: CompiledSegment,
  localTime: number,
  castById: Map<string, BlockingCastMember>,
): Omit<FrameState, 'time'> {
  const t = Math.min(Math.max(localTime, 0), segment.duration);
  const camera = cameraAt(segment, t);
  const resolver = makeResolver(segment.tracks, anchorPositions(segment.set), (at) =>
    cameraAt(segment, at),
  );
  const cast: CastFrame[] = [];
  for (const track of segment.tracks.values()) {
    const member = castById.get(track.id);
    if (!member) continue;
    cast.push({ id: track.id, member, ...track.sample(t, resolver) });
  }
  separate(cast);
  return {
    segment,
    localTime: t,
    camera,
    shot: segment.source.camera_override ? null : shotAt(segment, t),
    cast,
  };
}

export function compileBlocking(document: BlockingDocument): Timeline {
  const cast = document.cast ?? [];
  const castById = new Map(cast.map((member) => [member.id, member]));
  const setById = new Map((document.sets ?? []).map((set) => [set.id, set]));
  const fallbackSet = (heading: string): BlockingSet => ({
    id: 'fallback',
    heading,
    ground: 'floor',
    width_m: 10,
    depth_m: 10,
    props: [],
    anchors: [],
  });

  const segments: CompiledSegment[] = [];
  let cursor = 0;
  (document.segments ?? []).forEach((source, index) => {
    const set = setById.get(source.set_id) ?? fallbackSet(source.heading);
    segments.push(compileSegment(source, index, cursor, set, castById, document.aspect_ratio));
    cursor += source.duration_s;
  });
  const duration = cursor;

  const segmentAt = (time: number): CompiledSegment | null => {
    if (segments.length === 0) return null;
    const clamped = Math.min(Math.max(time, 0), duration);
    for (const segment of segments) {
      if (clamped < segment.start + segment.duration) return segment;
    }
    return segments.at(-1) ?? null;
  };

  return {
    duration,
    segments,
    cast,
    aspect: document.aspect_ratio,
    segmentAt,
    sample: (time) => {
      const segment = segmentAt(time);
      if (!segment) return null;
      return { time, ...sampleSegment(segment, time - segment.start, castById) };
    },
  };
}

export { markPosition };
