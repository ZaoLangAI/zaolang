import { describe, expect, it } from 'vitest';

import type { BlockingDocument, BlockingSegment, BlockingShot } from '../types';
import { CAMERA_MOVES, keysOf } from '../vocabulary';
import { fovFromLens, frameShot } from './camera';
import { compileBlocking } from './compile';
import { measureTimeline } from './quality';
import { angleDelta, length, sub } from './math';

const shot = (overrides: Partial<BlockingShot> = {}): BlockingShot => ({
  t0: 0,
  transition: 'cut',
  size: 'medium',
  lens_mm: 35,
  height: 'eye',
  side: 'front',
  subject: 'lin',
  over: null,
  move: { preset: 'static', intensity: 0.5, ease: 'in_out' },
  ...overrides,
});

const segment = (overrides: Partial<BlockingSegment> = {}): BlockingSegment => ({
  key: '便利店#0',
  heading: '便利店',
  set_id: 's1',
  source_hash: '0000000000000000',
  duration_s: 6,
  start: [
    {
      cast_id: 'lin',
      at: { anchor: null, x: 0, z: 0 },
      face: { target: null, deg: 0 },
      action: 'stand',
    },
    {
      cast_id: 'chen',
      at: { anchor: 'door', x: 3, z: 2 },
      face: { target: 'lin', deg: 0 },
      action: 'stand',
    },
  ],
  beats: [
    {
      cast_id: 'lin',
      t0: 1,
      t1: 3,
      action: 'walk',
      to: { anchor: null, x: 0, z: -2 },
      face: { target: 'chen', deg: 0 },
    },
    { cast_id: 'chen', t0: 2, t1: 4, action: 'talk', to: null, face: null },
  ],
  shots: [shot()],
  camera_override: null,
  ...overrides,
});

const documentWith = (segments: BlockingSegment[]): BlockingDocument => ({
  version: 1,
  script_hash: 'x',
  target_duration_s: 12,
  aspect_ratio: '9:16',
  sets: [
    {
      id: 's1',
      heading: '便利店',
      ground: 'floor',
      width_m: 8,
      depth_m: 6,
      props: [],
      anchors: [{ id: 'door', label: '门口', x: 3, z: 2 }],
    },
  ],
  cast: [
    { id: 'lin', name: '林夏', character_ref_id: null, color_index: 0, height_m: 1.65 },
    { id: 'chen', name: '陈默', character_ref_id: null, color_index: 1, height_m: 1.8 },
  ],
  segments,
});

describe('compileBlocking', () => {
  it('lays segments end to end and finds the one playing at a time', () => {
    const timeline = compileBlocking(
      documentWith([segment(), segment({ key: '便利店#1', duration_s: 5 })]),
    );
    expect(timeline.duration).toBe(11);
    expect(timeline.segmentAt(0)?.key).toBe('便利店#0');
    expect(timeline.segmentAt(6.5)?.key).toBe('便利店#1');
    expect(timeline.segmentAt(99)?.key).toBe('便利店#1');
    expect(timeline.sample(7)?.localTime).toBeCloseTo(1);
  });

  it('moves a walker from its mark to its destination and blends the base action', () => {
    const timeline = compileBlocking(documentWith([segment()]));
    const at = (t: number) => timeline.sample(t)!.cast.find((c) => c.id === 'lin')!;
    expect(at(0.5).position).toEqual([0, 0, 0]);
    expect(at(0.5).base).toBe('stand');
    expect(at(2).base).toBe('walk');
    expect(at(2).position[2]).toBeLessThan(0);
    expect(at(2).speed).toBeGreaterThan(0);
    expect(at(4).position).toEqual([0, 0, -2]);
    expect(at(4).base).toBe('stand');
    // After arriving, 林夏 turns to face 陈默 at the door.
    const facing = at(5.5).yaw;
    const towardChen = (Math.atan2(3 - 0, 2 - -2) * 180) / Math.PI;
    expect(Math.abs(angleDelta(facing, towardChen))).toBeLessThan(1);
  });

  it('layers a gesture with a fade and keeps it off outside its beat', () => {
    const timeline = compileBlocking(documentWith([segment()]));
    const chen = (t: number) => timeline.sample(t)!.cast.find((c) => c.id === 'chen')!;
    expect(chen(1).gesture).toBe('none');
    expect(chen(3).gesture).toBe('talk');
    expect(chen(3).gestureWeight).toBe(1);
    expect(chen(2.1).gestureWeight).toBeLessThan(1);
    expect(chen(5).gesture).toBe('none');
  });

  it('samples identically every time (the export depends on it)', () => {
    const doc = documentWith([
      segment({ shots: [shot({ move: { preset: 'handheld', intensity: 0.8, ease: 'linear' } })] }),
    ]);
    const a = compileBlocking(doc).sample(2.37)!;
    const b = compileBlocking(doc).sample(2.37)!;
    expect(a.camera).toEqual(b.camera);
    expect(a.cast).toEqual(b.cast);
  });

  it.each(keysOf(CAMERA_MOVES))('plays %s without leaving the set', (preset) => {
    const timeline = compileBlocking(
      documentWith([
        segment({ shots: [shot({ move: { preset, intensity: 1, ease: 'in_out' } })] }),
      ]),
    );
    for (const t of [0, 3, 6]) {
      const camera = timeline.sample(t)!.camera;
      expect(camera.position.every(Number.isFinite)).toBe(true);
      expect(camera.position[1]).toBeGreaterThan(0);
      expect(length(sub(camera.target, camera.position))).toBeGreaterThan(0.1);
    }
  });

  it('pushes in toward the subject and pulls out away from it', () => {
    const distanceAt = (preset: 'push_in' | 'pull_out', t: number) => {
      const timeline = compileBlocking(
        documentWith([
          segment({
            beats: [],
            shots: [shot({ move: { preset, intensity: 1, ease: 'linear' } })],
          }),
        ]),
      );
      const camera = timeline.sample(t)!.camera;
      return length(sub(camera.target, camera.position));
    };
    expect(distanceAt('push_in', 5.99)).toBeLessThan(distanceAt('push_in', 0));
    expect(distanceAt('pull_out', 5.99)).toBeGreaterThan(distanceAt('pull_out', 0));
  });

  it('prefers a manual camera override over the shot grammar', () => {
    const override = {
      start: { position: [1, 2, 3], target: [0, 1, 0], fov: 30 },
      end: { position: [1, 2, 5], target: [0, 1, 0], fov: 30 },
    };
    const timeline = compileBlocking(documentWith([segment({ camera_override: override })]));
    expect(timeline.sample(0)!.camera.position).toEqual([1, 2, 3]);
    expect(timeline.sample(6)!.camera.position).toEqual([1, 2, 5]);
  });
});

describe('frameShot', () => {
  const subject = { position: () => [0, 0, 0] as [number, number, number], height: 1.7, yaw: 0 };
  const context = { aspect: '16:9' as const, subject, over: null, groupWidth: 0, seedKey: 'k' };

  it('backs away for wider sizes and longer lenses', () => {
    const distance = (overrides: Partial<BlockingShot>) => {
      const pose = frameShot(shot(overrides), context);
      return length(sub(pose.target, pose.position));
    };
    expect(distance({ size: 'close' })).toBeLessThan(distance({ size: 'medium' }));
    expect(distance({ size: 'medium' })).toBeLessThan(distance({ size: 'full' }));
    expect(distance({ lens_mm: 85 })).toBeGreaterThan(distance({ lens_mm: 35 }));
  });

  it('puts a front camera in front of the subject and a left camera on their left', () => {
    expect(frameShot(shot(), context).position[2]).toBeGreaterThan(0);
    expect(frameShot(shot({ side: 'left' }), context).position[0]).toBeGreaterThan(0);
    expect(frameShot(shot({ height: 'high' }), context).position[1]).toBeGreaterThan(1.5);
  });

  it('turns the sensor upright for vertical video', () => {
    expect(fovFromLens(35, '9:16')).toBeGreaterThan(fovFromLens(35, '16:9'));
  });
});

describe('staging repairs', () => {
  const walled = (segments: BlockingSegment[]): BlockingDocument => {
    const doc = documentWith(segments);
    doc.sets![0]!.props = [
      {
        id: 'desk',
        primitive: 'box',
        label: '桌',
        color_role: 'furniture',
        position: [0, 0, -1],
        rotation_y_deg: 0,
        scale: [2, 0.8, 0.8],
      },
    ];
    return doc;
  };

  it('switches shots at their start times and glides into a continuous one', () => {
    const timeline = compileBlocking(
      documentWith([
        segment({
          shots: [
            shot({ size: 'wide' }),
            shot({ t0: 3, size: 'close', transition: 'cut' }),
            shot({ t0: 4.5, size: 'close', transition: 'continuous', side: 'left' }),
          ],
        }),
      ]),
    );
    expect(timeline.sample(1)!.shot?.index).toBe(0);
    expect(timeline.sample(3.2)!.shot?.index).toBe(1);
    const distance = (t: number) => {
      const camera = timeline.sample(t)!.camera;
      return length(sub(camera.target, camera.position));
    };
    expect(distance(3.2)).toBeLessThan(distance(1));
    // The continuous shot starts where the close-up left off, not at its own
    // framing — no jump at the boundary.
    const before = timeline.sample(4.49)!.camera.position;
    const after = timeline.sample(4.51)!.camera.position;
    expect(length(sub(after, before))).toBeLessThan(0.2);
  });

  it('keeps a walking subject in frame even on a static camera', () => {
    const walker = segment({
      start: [
        {
          cast_id: 'lin',
          at: { anchor: null, x: -2.5, z: 0 },
          face: { target: null, deg: 90 },
          action: 'stand',
        },
      ],
      beats: [
        {
          cast_id: 'lin',
          t0: 0.5,
          t1: 5.5,
          action: 'walk',
          to: { anchor: null, x: 2.5, z: 1 },
          face: null,
        },
      ],
      shots: [shot({ size: 'medium_close', subject: 'lin', side: 'front' })],
    });
    const [quality] = measureTimeline(compileBlocking(documentWith([walker])));
    expect(quality!.framedRatio).toBeGreaterThan(0.9);
  });

  it('walks around furniture instead of through it', () => {
    const crossing = segment({
      start: [
        {
          cast_id: 'lin',
          at: { anchor: null, x: 0, z: -2.5 },
          face: { target: null, deg: 0 },
          action: 'stand',
        },
      ],
      beats: [
        {
          cast_id: 'lin',
          t0: 0,
          t1: 5,
          action: 'walk',
          to: { anchor: null, x: 0, z: 0.8 },
          face: null,
        },
      ],
    });
    const timeline = compileBlocking(walled([crossing]));
    const [quality] = measureTimeline(timeline);
    expect(quality!.propPenetrationFrames).toBe(0);
    // It still gets there.
    const end = timeline.sample(5.9)!.cast[0]!.position;
    expect(Math.hypot(end[0], end[2] - 0.8)).toBeLessThan(0.5);
  });

  it('spreads people placed on the same mark and keeps walkers apart', () => {
    const crowded = segment({
      start: [
        {
          cast_id: 'lin',
          at: { anchor: null, x: 0, z: 0 },
          face: { target: null, deg: 0 },
          action: 'stand',
        },
        {
          cast_id: 'chen',
          at: { anchor: null, x: 0.1, z: 0 },
          face: { target: null, deg: 0 },
          action: 'stand',
        },
      ],
      beats: [
        {
          cast_id: 'chen',
          t0: 1,
          t1: 4,
          action: 'walk',
          to: { anchor: null, x: 0, z: 0 },
          face: null,
        },
      ],
    });
    const [quality] = measureTimeline(compileBlocking(documentWith([crowded])));
    expect(quality!.minCastDistance).toBeGreaterThan(0.5);
  });

  it('moves a camera that a wall would block', () => {
    const doc = documentWith([segment({ shots: [shot({ subject: 'lin', side: 'front' })] })]);
    // A wall right between the subject and where a front camera goes.
    doc.sets![0]!.props = [
      {
        id: 'wall',
        primitive: 'plane',
        label: '墙',
        color_role: 'wall',
        position: [0, 0, 1.2],
        rotation_y_deg: 0,
        scale: [3, 3, 1],
      },
    ];
    const [quality] = measureTimeline(compileBlocking(doc));
    expect(quality!.occludedRatio).toBe(0);
    expect(quality!.framedRatio).toBeGreaterThan(0.9);
  });
});
