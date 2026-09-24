import type {
  BlockingCastMember,
  BlockingDocument,
  BlockingSegment,
  BlockingSet,
  CameraPose,
  Vec3,
} from '../types';
import {
  fitPointsInFrame,
  frameShot,
  sampleOverride,
  sampleShot,
  type ShotContext,
  type ShotSubject,
} from './camera';
import { CastTrack, markPosition, type CastSample, type TargetResolver } from './tracks';

/**
 * `compileBlocking(document)` → a `Timeline` that can be sampled at any
 * episode time. This is the only place the semantic document becomes
 * motion; the three.js player and the MP4 exporter are both thin consumers
 * of `Timeline.sample`, which is what guarantees the exported reference
 * video matches what the author watched.
 */

export const CAMERA_TARGET = 'camera';
const DEFAULT_HEIGHT = 1.7;
const FIT_SAMPLES = [0, 0.25, 0.5, 0.75, 1];

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
  baseCamera: CameraPose;
  shotContext: ShotContext;
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

function compileSegment(
  source: BlockingSegment,
  index: number,
  start: number,
  set: BlockingSet,
  castById: Map<string, BlockingCastMember>,
  aspect: BlockingDocument['aspect_ratio'],
): CompiledSegment {
  const tracks = new Map<string, CastTrack>();
  for (const entry of source.start ?? []) {
    if (castById.has(entry.cast_id)) {
      tracks.set(entry.cast_id, new CastTrack(entry, source.beats ?? []));
    }
  }
  const anchors = anchorPositions(set);
  // First pass: facing the camera counts as facing +z, which is where the
  // framing below will put a front-side camera anyway. The real camera
  // position resolves `camera` facings at sample time.
  const provisional = makeResolver(tracks, anchors, null);

  const heightOf = (castId: string) => castById.get(castId)?.height_m ?? DEFAULT_HEIGHT;
  const subjectFor = (ref: string | null | undefined): ShotSubject | null => {
    if (!ref) return null;
    const track = tracks.get(ref);
    if (track) {
      return {
        position: (t) => track.position(t),
        height: heightOf(ref),
        yaw: track.yaw(0, provisional),
      };
    }
    const anchor = anchors.get(ref);
    if (anchor) return { position: () => anchor, height: 1.3, yaw: 0 };
    return null;
  };

  const onSet = [...tracks.values()];
  const origins = onSet.map((track) => track.position(0));
  const centroid: Vec3 = origins.length
    ? [
        origins.reduce((sum, p) => sum + p[0], 0) / origins.length,
        0,
        origins.reduce((sum, p) => sum + p[2], 0) / origins.length,
      ]
    : [0, 0, 0];
  const xs = origins.map((p) => p[0]);
  const subject = subjectFor(source.shot.subject);
  const groupWidth = subject || xs.length < 2 ? 0 : Math.max(...xs) - Math.min(...xs);
  const averageHeight = onSet.length
    ? onSet.reduce((sum, track) => sum + heightOf(track.id), 0) / onSet.length
    : DEFAULT_HEIGHT;

  const shotContext: ShotContext = {
    aspect,
    subject: subject ?? { position: () => centroid, height: averageHeight, yaw: 0 },
    over: subjectFor(source.shot.over),
    groupWidth,
    seedKey: source.key,
  };

  return {
    index,
    key: source.key,
    heading: source.heading,
    set,
    start,
    duration: source.duration_s,
    source,
    tracks,
    baseCamera: subject
      ? frameShot(source.shot, shotContext)
      : fitPointsInFrame(
          frameShot(source.shot, shotContext),
          // Everyone on set, wherever they walk to during the segment —
          // a subject-less shot is the establishing/group shot.
          onSet.flatMap((track) =>
            FIT_SAMPLES.flatMap((u) => {
              const at = track.position(u * source.duration_s);
              return [at, [at[0], heightOf(track.id) * 1.08, at[2]] as Vec3];
            }),
          ),
          aspect,
        ),
    shotContext,
  };
}

export function cameraAt(segment: CompiledSegment, localTime: number): CameraPose {
  const override = segment.source.camera_override;
  if (override) return sampleOverride(override, localTime, segment.duration);
  return sampleShot(
    segment.source.shot,
    segment.baseCamera,
    segment.shotContext,
    localTime,
    segment.duration,
  );
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
  return { segment, localTime: t, camera, cast };
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
