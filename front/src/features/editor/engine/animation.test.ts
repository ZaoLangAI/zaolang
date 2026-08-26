import { describe, expect, it } from 'vitest';

import { pointsFor, resolveNumberAtTime } from './animation';
import type { ElementAnimations } from './ports';

function animations(points: Array<{ at_ticks: number; value: number }>): ElementAnimations {
  return { channels: { opacity: { kind: 'number', points } } };
}

describe('resolveNumberAtTime', () => {
  it('falls back to the base value with no channel at all', () => {
    expect(resolveNumberAtTime(undefined, 'opacity', 1000, 50)).toBe(50);
  });

  it('falls back to the base value with an empty points list', () => {
    expect(resolveNumberAtTime(animations([]), 'opacity', 1000, 50)).toBe(50);
  });

  it('returns the single point value everywhere when only one point exists', () => {
    const value = resolveNumberAtTime(animations([{ at_ticks: 5000, value: 80 }]), 'opacity', 0, 50);
    expect(value).toBe(80);
  });

  it('interpolates linearly between two bracketing points', () => {
    const anims = animations([
      { at_ticks: 0, value: 0 },
      { at_ticks: 1000, value: 100 },
    ]);
    expect(resolveNumberAtTime(anims, 'opacity', 250, 0)).toBeCloseTo(25, 5);
    expect(resolveNumberAtTime(anims, 'opacity', 500, 0)).toBeCloseTo(50, 5);
    expect(resolveNumberAtTime(anims, 'opacity', 750, 0)).toBeCloseTo(75, 5);
  });

  it('holds the edge value outside the keyframed range', () => {
    const anims = animations([
      { at_ticks: 1000, value: 10 },
      { at_ticks: 2000, value: 90 },
    ]);
    expect(resolveNumberAtTime(anims, 'opacity', 0, 0)).toBe(10);
    expect(resolveNumberAtTime(anims, 'opacity', 5000, 0)).toBe(90);
  });

  it('interpolates correctly with points given out of order', () => {
    const anims = animations([
      { at_ticks: 1000, value: 100 },
      { at_ticks: 0, value: 0 },
    ]);
    expect(resolveNumberAtTime(anims, 'opacity', 500, 0)).toBeCloseTo(50, 5);
  });

  it('picks the channel matching the requested property, not just any channel', () => {
    const anims: ElementAnimations = {
      channels: {
        opacity: { kind: 'number', points: [{ at_ticks: 0, value: 100 }] },
        'transform.x_milli': { kind: 'number', points: [{ at_ticks: 0, value: 500 }] },
      },
    };
    expect(resolveNumberAtTime(anims, 'opacity', 0, 0)).toBe(100);
    expect(resolveNumberAtTime(anims, 'transform.x_milli', 0, 0)).toBe(500);
    expect(resolveNumberAtTime(anims, 'transform.y_milli', 0, 0)).toBe(0);
  });
});

describe('pointsFor', () => {
  it('returns an empty array when the channel is absent', () => {
    expect(pointsFor(undefined, 'opacity')).toEqual([]);
    expect(pointsFor({ channels: {} }, 'opacity')).toEqual([]);
  });

  it('returns the channel points as-is', () => {
    const points = [{ at_ticks: 0, value: 1 }];
    const anims = animations(points);
    expect(pointsFor(anims, 'opacity')).toBe(anims.channels.opacity!.points);
  });
});
