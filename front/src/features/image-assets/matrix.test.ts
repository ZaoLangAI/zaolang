import { describe, expect, it } from 'vitest';

import { matrixCellCount, matrixGrid } from './matrix';

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

describe('matrixGrid', () => {
  const cell = (presets: Record<string, string>) => ({ presets, id: JSON.stringify(presets) });

  it('puts the first two picked axes on rows and columns', () => {
    const cells = [
      cell({ lighting: 'day', weather: 'rain' }),
      cell({ lighting: 'day', weather: 'snow' }),
      cell({ lighting: 'dusk', weather: 'rain' }),
      cell({ lighting: 'dusk', weather: 'snow' }),
    ];
    const grid = matrixGrid({ lighting: ['day', 'dusk'], weather: ['rain', 'snow'] }, cells);
    expect(grid?.rowAxis).toBe('lighting');
    expect(grid?.colAxis).toBe('weather');
    expect(grid?.pages).toHaveLength(1);
    expect(grid?.pages[0]?.rows.map((row) => row.map((c) => c?.id))).toEqual([
      [cells[0]?.id, cells[1]?.id],
      [cells[2]?.id, cells[3]?.id],
    ]);
  });

  it('pages over the remaining axes and skips empty ones', () => {
    const cells = [
      cell({ lighting: 'day', state: 'intact', period: 'republic' }),
      cell({ lighting: 'day', state: 'ruins', period: 'republic' }),
      cell({ lighting: 'day', state: 'intact', period: '1980s' }),
      cell({ lighting: 'day', state: 'ruins', period: '1980s' }),
    ];
    const grid = matrixGrid(
      { lighting: ['day'], weather: [], state: ['intact', 'ruins'], period: ['republic', '1980s'] },
      cells,
    );
    expect(grid?.colAxis).toBe('state');
    expect(grid?.pageAxes).toEqual(['period']);
    expect(grid?.pages.map((page) => page.presets)).toEqual([
      { period: 'republic' },
      { period: '1980s' },
    ]);
    expect(grid?.pages[1]?.rows[0]?.map((c) => c?.id)).toEqual([cells[2]?.id, cells[3]?.id]);
  });

  it('is a single column for one axis, and null for none', () => {
    const grid = matrixGrid({ weather: ['rain', 'snow'] }, [cell({ weather: 'rain' })]);
    expect(grid?.colAxis).toBeNull();
    expect(grid?.pages[0]?.rows.map((row) => row.map((c) => c?.id ?? null))).toEqual([
      [JSON.stringify({ weather: 'rain' })],
      [null],
    ]);
    expect(matrixGrid({}, [])).toBeNull();
  });
});
