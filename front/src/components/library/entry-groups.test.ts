import { describe, expect, it } from 'vitest';

import type { AssetEntry } from '@/lib/api/types';

import { candidateCount, groupEntries } from './entry-groups';

function entry(id: string, overrides: Partial<AssetEntry>): AssetEntry {
  return {
    id,
    asset_id: `ast_${id}`,
    entry_type: 'other',
    status: 'approved',
    is_anchor: false,
    created_at: '2026-10-02T00:00:00Z',
    ...overrides,
  } as AssetEntry;
}

describe('groupEntries', () => {
  it('groups a look by role and puts candidates after the approved image', () => {
    const groups = groupEntries('character', [
      entry('c1', { entry_type: 'character_sheet', status: 'candidate' }),
      entry('s1', { entry_type: 'character_sheet' }),
      entry('v1', { entry_type: 'view', view: 'side' }),
      entry('p1', { entry_type: 'prop' }),
      entry('portrait', { entry_type: 'identity_portrait' }),
    ]);
    expect(groups.map((g) => [g.key, g.entries.map((e) => e.id), g.candidates])).toEqual([
      ['portrait', ['portrait'], 0],
      ['sheet', ['s1', 'c1'], 1],
      ['view', ['v1'], 0],
      ['detail', ['p1'], 0],
    ]);
  });

  it('groups a scene variant into master plates, shots and the rest', () => {
    const groups = groupEntries('scene', [
      entry('shot', { entry_type: 'shot' }),
      entry('master', { entry_type: 'master' }),
    ]);
    expect(groups.map((g) => g.key)).toEqual(['master', 'shot']);
  });
});

describe('candidateCount', () => {
  it('counts only candidates', () => {
    expect(candidateCount([entry('a', {}), entry('b', { status: 'candidate' })])).toBe(1);
  });
});
