import type { ColorRole, Ground } from './types';

/**
 * Render colours for the 3D blockout.
 *
 * Deliberately *not* theme tokens: the viewport is a render, and the same
 * render is exported frame-for-frame as the reference video a model reads.
 * A light theme and a dark theme must produce the identical clip, so these
 * are fixed values in one module rather than CSS variables. The page chrome
 * around the viewport still uses theme tokens only.
 *
 * The look is a classic 白膜: near-white matte set dressing on a light grey
 * studio, with the cast as the only saturated objects — so a video model can
 * tell who is who, and nothing else competes for attention.
 */

export const STUDIO_BACKGROUND = 0xc9ccd0;
export const GRID_MAJOR = 0x9aa0a6;
export const GRID_MINOR = 0xb4b9be;
export const ANCHOR_MARK = 0x5f6b7a;
export const SELECTION = 0xff795b;

export const GROUND_COLORS: Record<Ground, number> = {
  floor: 0xe4e2de,
  street: 0xbfc1c3,
  grass: 0xcfd9c7,
  sand: 0xe6dcc8,
  water: 0xc3d3de,
  void: 0xd3d5d8,
};

export const PROP_COLORS: Record<ColorRole, number> = {
  wall: 0xf2f1ee,
  floor: 0xdedbd6,
  furniture: 0xe9e6e0,
  door: 0xd8d2c8,
  window: 0xd5e0e8,
  vehicle: 0xd9dcdf,
  nature: 0xdbe3d5,
  accent: 0xe8dcd0,
};

/**
 * Eight cast colours, each with the colour *name* the video prompt's legend
 * quotes ("红色人偶 = 林夏"), so the index is stable across a whole episode
 * (the backend assigns `color_index` once per character and keeps it).
 */
export const CAST_COLORS: readonly { hex: number; css: string; nameKey: string }[] = [
  { hex: 0xd64545, css: '#d64545', nameKey: 'red' },
  { hex: 0x3f7fd6, css: '#3f7fd6', nameKey: 'blue' },
  { hex: 0x3fa65a, css: '#3fa65a', nameKey: 'green' },
  { hex: 0xe0b12e, css: '#e0b12e', nameKey: 'yellow' },
  { hex: 0x8a55c9, css: '#8a55c9', nameKey: 'purple' },
  { hex: 0xe57a2e, css: '#e57a2e', nameKey: 'orange' },
  { hex: 0x2fb3bd, css: '#2fb3bd', nameKey: 'cyan' },
  { hex: 0xd65a9e, css: '#d65a9e', nameKey: 'pink' },
];

export function castColor(index: number) {
  const size = CAST_COLORS.length;
  return CAST_COLORS[((index % size) + size) % size]!;
}
