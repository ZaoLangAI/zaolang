import { describe, expect, it } from 'vitest';

import { toggledKinds, withDefaultThreshold } from './asset-consistency';

describe('withDefaultThreshold', () => {
  it('sets the default and keeps per-type thresholds', () => {
    expect(
      withDefaultThreshold({ character: { expression_sheet: 55 } }, 'character', '70'),
    ).toEqual({ character: { expression_sheet: 55, '*': 70 } });
  });

  it('rounds to an integer and keeps 0 as a real threshold', () => {
    expect(withDefaultThreshold({}, 'scene', '64.6')).toEqual({ scene: { '*': 65 } });
    expect(withDefaultThreshold({}, 'prop', '0')).toEqual({ prop: { '*': 0 } });
  });

  it('clearing the field removes the default and an emptied kind', () => {
    const thresholds = { scene: { '*': 60 }, prop: { '*': 50, master: 40 } };
    expect(withDefaultThreshold(thresholds, 'scene', ' ')).toEqual({
      prop: { '*': 50, master: 40 },
    });
    expect(withDefaultThreshold(thresholds, 'prop', '')).toEqual({
      scene: { '*': 60 },
      prop: { master: 40 },
    });
  });

  it('does not mutate its input', () => {
    const thresholds = { scene: { '*': 60 } };
    withDefaultThreshold(thresholds, 'scene', '');
    expect(thresholds).toEqual({ scene: { '*': 60 } });
  });
});

describe('toggledKinds', () => {
  it('keeps the canonical order', () => {
    expect(toggledKinds(['prop'], 'character', true)).toEqual(['character', 'prop']);
    expect(toggledKinds(['character', 'scene', 'prop'], 'scene', false)).toEqual([
      'character',
      'prop',
    ]);
  });
});
