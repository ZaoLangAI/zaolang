import { describe, expect, it } from 'vitest';

import { matchesPresetFilter, matrixCellCount } from './matrix';

describe('matrixCellCount', () => {
  it('multiplies the axes that have values and ignores the empty ones', () => {
    expect(
      matrixCellCount({ lighting: ['day', 'dusk'], weather: [], state: ['intact', 'ruins'] }),
    ).toBe(4);
  });

  it('is zero when nothing is picked', () => {
    expect(matrixCellCount({})).toBe(0);
  });
});

describe('matchesPresetFilter', () => {
  it('matches every filtered axis and ignores the empty ones', () => {
    const presets = { lighting: 'dusk', weather: 'rain' };
    expect(matchesPresetFilter(presets, {})).toBe(true);
    expect(matchesPresetFilter(presets, { lighting: 'dusk' })).toBe(true);
    expect(matchesPresetFilter(presets, { lighting: 'dusk', weather: 'snow' })).toBe(false);
    expect(matchesPresetFilter(undefined, { state: 'ruins' })).toBe(false);
  });
});
