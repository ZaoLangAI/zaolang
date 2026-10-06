import type { AssetEntry, CameraPose } from '@/lib/api/types';

/** Mirrors `app.domain.image_assets.camera` (the fal multi-angle grid):
 * 0 = the subject faces the camera, 90 = its right side, 180 = its back
 * (a scene's reverse shot), 270 = its left. */
export const AZIMUTHS = [0, 45, 90, 135, 180, 225, 270, 315] as const;
export const ELEVATIONS = [-30, 0, 30, 60] as const;
export const DISTANCES = ['close', 'medium', 'wide'] as const;
export const MAX_CAMERA_POSES = 8;

export type Distance = (typeof DISTANCES)[number];

export function pose(azimuth: number, elevation = 0, distance: Distance = 'medium'): CameraPose {
  return { azimuth, elevation, distance };
}

function snapTo<T extends number>(values: readonly T[], value: number, wrap = false): T {
  let best = values[0] as T;
  let bestGap = Infinity;
  for (const candidate of values) {
    let gap = Math.abs(candidate - value);
    if (wrap) gap = Math.min(gap, 360 - gap);
    if (gap < bestGap) {
      best = candidate;
      bestGap = gap;
    }
  }
  return best;
}

/** `value` moved onto the grid (mirrors `camera.snap`). */
export function snapPose(value: CameraPose): CameraPose {
  return {
    azimuth: snapTo(AZIMUTHS, ((value.azimuth % 360) + 360) % 360, true),
    elevation: snapTo(ELEVATIONS, value.elevation ?? 0),
    distance: DISTANCES.includes(value.distance as Distance) ? value.distance : 'medium',
  };
}

/** `azimuth|elevation|distance` on the grid — one slot per key. */
export function poseKey(value: CameraPose): string {
  const { azimuth, elevation, distance } = snapPose(value);
  return `${azimuth}|${elevation}|${distance}`;
}

const VIEW_POSES: Record<string, CameraPose> = {
  front: pose(0),
  side: pose(90),
  back: pose(180),
  three_quarter: pose(45),
  reverse: pose(180),
};

/** The viewpoint an image shows — its stored pose, else what its coarse
 * `view` stands for; a character sheet is the front. Mirrors
 * `asset_variants.service.entry_pose`. */
export function entryPose(entry: AssetEntry): CameraPose | null {
  if (entry.camera) return entry.camera;
  if (entry.entry_type === 'character_sheet') return pose(0);
  if (entry.entry_type === 'view' || entry.entry_type === 'shot') {
    return entry.view ? (VIEW_POSES[entry.view] ?? null) : null;
  }
  return null;
}
