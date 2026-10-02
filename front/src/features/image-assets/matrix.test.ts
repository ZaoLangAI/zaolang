import { describe, expect, it } from 'vitest';

import { matrixCellCount } from './matrix';

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
