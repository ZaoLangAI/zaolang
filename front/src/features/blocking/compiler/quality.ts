import type { Vec3 } from '../types';
import { ASPECT_WIDTH_OVER_HEIGHT } from './camera';
import type { Timeline } from './compile';
import { cross, DEG, normalize, sub } from './math';
import { footprintContains, lineOfSightClear } from './obstacles';

/**
 * Measurable blockout quality — the failure modes authors actually report
 * (a static camera, frames with nobody in them, people walking through
 * each other or the furniture), scored on a compiled timeline. Used by the
 * tests to pin behaviour, and handy for checking a real episode.
 */
export interface SegmentQuality {
  key: string;
  frames: number;
  /** Share of frames where the shot's subject (or, for a group shot,
   * everyone) is inside the picture. */
  framedRatio: number;
  /** Share of frames where something solid is between the lens and the
   * subject. */
  occludedRatio: number;
  /** Closest any two cast members come, metres (Infinity for one person). */
  minCastDistance: number;
  /** Frames in which somebody stands inside a piece of furniture. */
  propPenetrationFrames: number;
  /** How far the camera travels and turns across the segment. */
  cameraTravel: number;
  cameraTurnDeg: number;
  shots: number;
}

const UP: Vec3 = [0, 1, 0];

function projectsInside(
  camera: { position: Vec3; target: Vec3; fov: number },
  point: Vec3,
  aspect: number,
  margin = 0.96,
): boolean {
  const forward = normalize(sub(camera.target, camera.position));
  const right = normalize(cross(forward, UP));
  const up = cross(right, forward);
  const v = sub(point, camera.position);
  const depth = v[0] * forward[0] + v[1] * forward[1] + v[2] * forward[2];
  if (depth <= 0.05) return false;
  const tanV = Math.tan((camera.fov * DEG) / 2) * margin;
  const x = (v[0] * right[0] + v[1] * right[1] + v[2] * right[2]) / depth;
  const y = (v[0] * up[0] + v[1] * up[1] + v[2] * up[2]) / depth;
  return Math.abs(x) <= tanV * aspect && Math.abs(y) <= tanV;
}

export function measureTimeline(timeline: Timeline, fps = 6): SegmentQuality[] {
  const aspect = ASPECT_WIDTH_OVER_HEIGHT[timeline.aspect];
  return timeline.segments.map((segment) => {
    const frames = Math.max(1, Math.round(segment.duration * fps));
    let framed = 0;
    let occluded = 0;
    let penetration = 0;
    let minDistance = Infinity;
    let travel = 0;
    let turn = 0;
    let previous: { position: Vec3; forward: Vec3 } | null = null;
    const solid = segment.obstacles.filter((o) => !o.walkable && o.y0 <= 0.6 && o.y1 - o.y0 >= 0.3);

    for (let i = 0; i < frames; i += 1) {
      const frame = timeline.sample(segment.start + (i + 0.5) / fps);
      if (!frame || frame.segment !== segment) continue;
      const camera = frame.camera;
      const subjectId = frame.shot?.source.subject ?? null;
      const people = frame.cast.filter((cast) => !subjectId || cast.id === subjectId);
      const chest = (cast: (typeof frame.cast)[number]): Vec3 => [
        cast.position[0],
        cast.member.height_m * 0.72,
        cast.position[2],
      ];
      const head = (cast: (typeof frame.cast)[number]): Vec3 => [
        cast.position[0],
        cast.member.height_m * 0.93,
        cast.position[2],
      ];
      if (
        people.length > 0 &&
        people.every(
          (cast) =>
            projectsInside(camera, chest(cast), aspect) ||
            projectsInside(camera, head(cast), aspect),
        )
      ) {
        framed += 1;
      }
      if (
        people.some((cast) => !lineOfSightClear(segment.obstacles, camera.position, chest(cast)))
      ) {
        occluded += 1;
      }
      for (let a = 0; a < frame.cast.length; a += 1) {
        const p = frame.cast[a]!.position;
        if (solid.some((o) => footprintContains(o, p[0], p[2], -0.05))) penetration += 1;
        for (let b = a + 1; b < frame.cast.length; b += 1) {
          const q = frame.cast[b]!.position;
          minDistance = Math.min(minDistance, Math.hypot(p[0] - q[0], p[2] - q[2]));
        }
      }
      const forward = normalize(sub(camera.target, camera.position));
      if (previous) {
        travel += Math.hypot(...sub(camera.position, previous.position));
        const dot = Math.min(
          1,
          Math.max(
            -1,
            forward[0] * previous.forward[0] +
              forward[1] * previous.forward[1] +
              forward[2] * previous.forward[2],
          ),
        );
        turn += Math.acos(dot) / DEG;
      }
      previous = { position: camera.position, forward };
    }
    return {
      key: segment.key,
      frames,
      framedRatio: framed / frames,
      occludedRatio: occluded / frames,
      minCastDistance: minDistance,
      propPenetrationFrames: penetration,
      cameraTravel: travel,
      cameraTurnDeg: turn,
      shots: segment.shots.length,
    };
  });
}
