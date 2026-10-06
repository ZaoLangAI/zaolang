import type { CameraPose } from '@/lib/api/types';

import { type Distance, snapPose } from './camera';

/** Where the panorama viewer looks (`PanoramaHandle.readPosition`): degrees,
 * yaw 0 = the middle of the equirectangular image (the master's own
 * direction), positive = turned right; pitch positive = looking up; `fov`
 * the vertical field of view. */
export interface PanoramaPosition {
  yaw: number;
  pitch: number;
  fov: number;
}

/** Vertical fields of view (the viewer allows 25°–110°) at or below which a
 * cut is a close shot, at or above which a wide one — the same bands as the
 * canvas director's framing sentence. */
export const CLOSE_FOV = 40;
export const WIDE_FOV = 80;

export function fovDistance(fov: number): Distance {
  if (fov <= CLOSE_FOV) return 'close';
  if (fov >= WIDE_FOV) return 'wide';
  return 'medium';
}

/**
 * The camera pose a shot cut from the panorama is filed under, snapped to
 * the grid (`camera.ts`): turning right by `yaw` is the scene's azimuth
 * (180 = the reverse shot); looking *down* is a high camera, so elevation is
 * the negated pitch; the field of view picks the distance.
 */
export function panoramaPose(position: PanoramaPosition): CameraPose {
  return snapPose({
    azimuth: Math.round(position.yaw),
    elevation: -Math.round(position.pitch),
    distance: fovDistance(position.fov),
  });
}

/** The 精修 instruction for a cut (`…/entries/{id}:adjust`). */
export const REFINE_INSTRUCTION =
  '去除全景畸变，按此机位重绘为单镜头画面，保持场景结构、陈设与光线不变';
