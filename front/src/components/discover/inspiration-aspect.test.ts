import { describe, expect, it } from 'vitest';

import { tileRatio } from './inspiration-aspect';

describe('tileRatio', () => {
  it('falls back to 16:9 when the asset never recorded a size', () => {
    expect(tileRatio(null, null)).toBe(16 / 9);
    expect(tileRatio(1920, 0)).toBe(16 / 9);
  });

  it('keeps a generated landscape or portrait frame', () => {
    expect(tileRatio(1920, 1080)).toBeCloseTo(16 / 9);
    expect(tileRatio(1080, 1920)).toBeCloseTo(9 / 16);
  });

  it('clamps outliers so one tile cannot swallow a column', () => {
    expect(tileRatio(4000, 1000)).toBeCloseTo(21 / 9);
    expect(tileRatio(1000, 4000)).toBeCloseTo(9 / 16);
  });
});
