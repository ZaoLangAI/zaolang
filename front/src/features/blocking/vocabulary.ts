import type { CameraHeight, CameraMove, CameraSide, CastAction, MoveEase, ShotSize } from './types';

/**
 * The closed preset vocabulary, keyed exhaustively over the generated unions:
 * a preset the backend adds (`back/app/domain/blocking/vocabulary.py`) fails
 * typecheck here until it has a label and, for moves, a default intensity.
 * The label is an i18n key under `blockingStudio.vocab`.
 */

export const CAMERA_MOVES: Record<CameraMove, { labelKey: string; defaultIntensity: number }> = {
  static: { labelKey: 'move.static', defaultIntensity: 0 },
  push_in: { labelKey: 'move.push_in', defaultIntensity: 0.4 },
  pull_out: { labelKey: 'move.pull_out', defaultIntensity: 0.4 },
  pan_left: { labelKey: 'move.pan_left', defaultIntensity: 0.4 },
  pan_right: { labelKey: 'move.pan_right', defaultIntensity: 0.4 },
  tilt_up: { labelKey: 'move.tilt_up', defaultIntensity: 0.4 },
  tilt_down: { labelKey: 'move.tilt_down', defaultIntensity: 0.4 },
  truck_left: { labelKey: 'move.truck_left', defaultIntensity: 0.4 },
  truck_right: { labelKey: 'move.truck_right', defaultIntensity: 0.4 },
  follow: { labelKey: 'move.follow', defaultIntensity: 0.5 },
  orbit_cw: { labelKey: 'move.orbit_cw', defaultIntensity: 0.4 },
  orbit_ccw: { labelKey: 'move.orbit_ccw', defaultIntensity: 0.4 },
  crane_up: { labelKey: 'move.crane_up', defaultIntensity: 0.4 },
  crane_down: { labelKey: 'move.crane_down', defaultIntensity: 0.4 },
  handheld: { labelKey: 'move.handheld', defaultIntensity: 0.3 },
};

export const SHOT_SIZES: Record<ShotSize, { labelKey: string }> = {
  extreme_wide: { labelKey: 'size.extreme_wide' },
  wide: { labelKey: 'size.wide' },
  full: { labelKey: 'size.full' },
  medium: { labelKey: 'size.medium' },
  medium_close: { labelKey: 'size.medium_close' },
  close: { labelKey: 'size.close' },
  extreme_close: { labelKey: 'size.extreme_close' },
};

export const CAMERA_HEIGHTS: Record<CameraHeight, { labelKey: string }> = {
  ground: { labelKey: 'height.ground' },
  low: { labelKey: 'height.low' },
  eye: { labelKey: 'height.eye' },
  high: { labelKey: 'height.high' },
  overhead: { labelKey: 'height.overhead' },
};

export const CAMERA_SIDES: Record<CameraSide, { labelKey: string }> = {
  front: { labelKey: 'side.front' },
  left: { labelKey: 'side.left' },
  right: { labelKey: 'side.right' },
  back: { labelKey: 'side.back' },
  ots_left: { labelKey: 'side.ots_left' },
  ots_right: { labelKey: 'side.ots_right' },
};

export const CAST_ACTIONS: Record<CastAction, { labelKey: string }> = {
  stand: { labelKey: 'action.stand' },
  sit: { labelKey: 'action.sit' },
  walk: { labelKey: 'action.walk' },
  run: { labelKey: 'action.run' },
  turn: { labelKey: 'action.turn' },
  point: { labelKey: 'action.point' },
  talk: { labelKey: 'action.talk' },
  wave: { labelKey: 'action.wave' },
  kneel: { labelKey: 'action.kneel' },
  fall: { labelKey: 'action.fall' },
  pickup: { labelKey: 'action.pickup' },
  hug: { labelKey: 'action.hug' },
  fight: { labelKey: 'action.fight' },
};

export const MOVE_EASES: Record<MoveEase, { labelKey: string }> = {
  linear: { labelKey: 'ease.linear' },
  in_out: { labelKey: 'ease.in_out' },
};

export const LENS_PRESETS_MM = [18, 24, 35, 50, 85, 135] as const;

/** Keys in declaration order — what pickers iterate. */
export function keysOf<K extends string>(record: Record<K, unknown>): K[] {
  return Object.keys(record) as K[];
}
