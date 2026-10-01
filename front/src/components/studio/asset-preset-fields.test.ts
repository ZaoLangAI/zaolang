import { describe, expect, it } from 'vitest';

import { sceneVariantCombos } from './asset-preset-fields';

describe('sceneVariantCombos', () => {
  it('varies one axis and keeps the others fixed', () => {
    expect(
      sceneVariantCombos({ state: 'damage_medium', lighting: 'day' }, 'lighting', ['day', 'dusk']),
    ).toEqual([
      { lighting: 'day', weather: null, state: 'damage_medium', period: null },
      { lighting: 'dusk', weather: null, state: 'damage_medium', period: null },
    ]);
  });

  it('is null until the group has at least two values', () => {
    expect(sceneVariantCombos({}, 'weather', ['rain'])).toBeNull();
    expect(sceneVariantCombos({}, null, ['rain', 'snow'])).toBeNull();
  });
});
