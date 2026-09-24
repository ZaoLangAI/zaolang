import { describe, expect, it } from 'vitest';

import { applyEdit, normalizeDeg } from './edits';
import type { BlockingDocument } from './types';

const document: BlockingDocument = {
  version: 1,
  script_hash: 'x',
  target_duration_s: 6,
  aspect_ratio: '9:16',
  sets: [
    {
      id: 's1',
      heading: '场',
      ground: 'floor',
      width_m: 8,
      depth_m: 6,
      props: [
        {
          id: 'desk',
          primitive: 'box',
          label: '桌',
          color_role: 'furniture',
          position: [0, 0, 0],
          rotation_y_deg: 0,
          scale: [1, 1, 1],
        },
      ],
      anchors: [],
    },
  ],
  cast: [{ id: 'lin', name: '林夏', character_ref_id: null, color_index: 0, height_m: 1.7 }],
  segments: [
    {
      key: '场#0',
      heading: '场',
      set_id: 's1',
      source_hash: '0',
      duration_s: 6,
      start: [
        {
          cast_id: 'lin',
          at: { anchor: 'door', x: 1, z: 1 },
          face: { target: 'camera', deg: 0 },
          action: 'stand',
        },
      ],
      beats: [],
      shot: {
        size: 'medium',
        lens_mm: 35,
        height: 'eye',
        side: 'front',
        subject: 'lin',
        over: null,
        move: { preset: 'static', intensity: 0.5, ease: 'in_out' },
      },
      camera_override: {
        start: { position: [0, 1.6, 4], target: [0, 1, 0], fov: 40 },
        end: null,
      },
    },
  ],
};

describe('applyEdit', () => {
  it('moves a prop without touching anything else', () => {
    const next = applyEdit(document, {
      kind: 'prop',
      setId: 's1',
      propId: 'desk',
      position: [1.23456, 0, -2],
      rotationYDeg: 90.00001,
      scale: [2, 1, 1],
    });
    expect(next.sets?.[0]?.props?.[0]).toMatchObject({
      position: [1.235, 0, -2],
      rotation_y_deg: 90,
      scale: [2, 1, 1],
    });
    expect(next.segments).toBe(document.segments);
    expect(document.sets?.[0]?.props?.[0]?.position).toEqual([0, 0, 0]);
  });

  it('turns a dragged mark into free coordinates and keeps facing unless turned', () => {
    const moved = applyEdit(document, {
      kind: 'cast-start',
      segmentKey: '场#0',
      castId: 'lin',
      x: 2,
      z: -1,
      yawDeg: null,
    });
    const entry = moved.segments?.[0]?.start?.[0];
    expect(entry?.at).toEqual({ anchor: null, x: 2, z: -1 });
    expect(entry?.face).toEqual({ target: 'camera', deg: 0 });

    const turned = applyEdit(document, {
      kind: 'cast-start',
      segmentKey: '场#0',
      castId: 'lin',
      x: 1,
      z: 1,
      yawDeg: 270,
    });
    expect(turned.segments?.[0]?.start?.[0]?.face).toEqual({ target: null, deg: -90 });
  });

  it('hands the camera back to the shot grammar when a preset is picked', () => {
    const next = applyEdit(document, {
      kind: 'shot',
      segmentKey: '场#0',
      shot: { ...document.segments![0]!.shot, size: 'close' },
    });
    expect(next.segments?.[0]?.shot.size).toBe('close');
    expect(next.segments?.[0]?.camera_override).toBeNull();
  });

  it('sets and clears a manual camera', () => {
    const cleared = applyEdit(document, {
      kind: 'camera-override',
      segmentKey: '场#0',
      override: null,
    });
    expect(cleared.segments?.[0]?.camera_override).toBeNull();
  });

  it('normalizes yaw into (-180, 180]', () => {
    expect(normalizeDeg(270)).toBe(-90);
    expect(normalizeDeg(-190)).toBe(170);
    expect(normalizeDeg(180)).toBe(180);
  });
});
