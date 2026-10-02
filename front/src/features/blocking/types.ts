import type { components } from '@/lib/api/schema';

/**
 * Named aliases for the generated 白膜 schema (`back/app/api/schemas/blocking.py`).
 * The unions (`CameraMove`, `CastAction`, …) come straight from the backend's
 * `Literal` vocabularies, so a preset added there is a compile error here
 * until `vocabulary.ts` handles it.
 */
type S = components['schemas'];

export type BlockingDocument = S['BlockingDocument'];
export type BlockingState = S['BlockingState'];
export type BlockingSet = S['BlockingSet'];
export type BlockingProp = S['BlockingProp'];
export type BlockingAnchor = S['BlockingAnchor'];
export type BlockingCastMember = S['BlockingCastMember'];
export type BlockingSegment = S['BlockingSegment'];
export type BlockingStartEntry = S['BlockingStartEntry'];
export type BlockingBeat = S['BlockingBeat'];
export type BlockingMark = S['BlockingMark'];
export type BlockingFacing = S['BlockingFacing'];
export type BlockingShot = S['BlockingShot'];
export type BlockingCameraPose = S['BlockingCameraPose'];
export type BlockingCameraOverride = S['BlockingCameraOverride'];

export type AspectRatio = BlockingDocument['aspect_ratio'];
export type Ground = BlockingSet['ground'];
export type Primitive = BlockingProp['primitive'];
export type ColorRole = BlockingProp['color_role'];
export type CastAction = BlockingStartEntry['action'];
export type ShotSize = BlockingShot['size'];
export type CameraHeight = BlockingShot['height'];
export type CameraSide = BlockingShot['side'];
export type CameraMove = BlockingShot['move']['preset'];
export type MoveEase = BlockingShot['move']['ease'];

export type Vec3 = [number, number, number];

export interface CameraPose {
  position: Vec3;
  target: Vec3;
  /** Vertical field of view, degrees. */
  fov: number;
}
