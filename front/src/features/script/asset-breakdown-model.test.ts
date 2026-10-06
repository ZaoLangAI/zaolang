import { describe, expect, it } from 'vitest';

import type { ScriptBreakdown, ScriptBreakdownItem } from '@/lib/api/types';

import {
  applyItems,
  breakdownReducer,
  createCounts,
  EMPTY_BREAKDOWN,
  incompleteRows,
  nothingToApply,
  quoteLines,
  rowKey,
  rowsOf,
  type BreakdownKind,
  type BreakdownState,
} from './asset-breakdown-model';

function item(
  overrides: Partial<ScriptBreakdownItem> & Pick<ScriptBreakdownItem, 'kind' | 'name'>,
) {
  return {
    description: '',
    headings: [],
    matches: [],
    linked_card_id: null,
    ...overrides,
  } satisfies ScriptBreakdownItem;
}

const BREAKDOWN: ScriptBreakdown = {
  degraded: false,
  characters: [
    item({ kind: 'character', name: '林夏', description: '齐肩黑发', age_stage: 'youth' }),
    item({
      kind: 'character',
      name: '顾沉',
      matches: [{ id: 'sk_gu', name: '顾沉' }],
    }),
  ],
  scenes: [
    item({
      kind: 'scene',
      name: '便利店',
      headings: ['第一场', '第三场'],
      period: 'contemporary',
      lighting: 'night_interior',
      linked_card_id: 'sk_store',
    }),
    item({ kind: 'scene', name: '书房', headings: ['第二场'] }),
  ],
  props: [item({ kind: 'prop', name: '玉佩', description: '碎玉', headings: ['第一场'] })],
};

function loaded(kinds: readonly BreakdownKind[] = ['character', 'scene', 'prop']): BreakdownState {
  return breakdownReducer(EMPTY_BREAKDOWN, { type: 'load', breakdown: BREAKDOWN, kinds });
}

const key = (kind: ScriptBreakdownItem['kind'], name: string) => rowKey({ kind, name });

describe('breakdownReducer load', () => {
  it('links what is already linked or same-named and creates the rest', () => {
    const state = loaded();
    expect(state.rows.map((row) => [row.key, row.action, row.cardId])).toEqual([
      ['character:林夏', 'create', null],
      ['character:顾沉', 'link', 'sk_gu'],
      ['scene:便利店', 'link', 'sk_store'],
      ['scene:书房', 'create', null],
      ['prop:玉佩', 'create', null],
    ]);
  });

  it('skips the kinds the dialog was not opened for', () => {
    const state = loaded(['prop']);
    expect(rowsOf(state, 'prop').map((row) => row.action)).toEqual(['create']);
    expect(rowsOf(state, 'scene').map((row) => row.action)).toEqual(['skip', 'skip']);
    expect(applyItems(state).map((entry) => entry.name)).toEqual(['玉佩']);
  });
});

describe('breakdownReducer choices', () => {
  it('never creates a character whose name is taken', () => {
    const state = breakdownReducer(loaded(), {
      type: 'action',
      key: key('character', '顾沉'),
      action: 'create',
    });
    expect(rowsOf(state, 'character')[1]?.action).toBe('link');
    const column = breakdownReducer(state, { type: 'column', kind: 'character', action: 'create' });
    expect(rowsOf(column, 'character').map((row) => row.action)).toEqual(['create', 'link']);
  });

  it('a link with no card is incomplete until one is picked', () => {
    let state = breakdownReducer(loaded(), {
      type: 'action',
      key: key('scene', '书房'),
      action: 'link',
    });
    expect(incompleteRows(state).map((row) => row.key)).toEqual(['scene:书房']);
    state = breakdownReducer(state, {
      type: 'card',
      key: key('scene', '书房'),
      cardId: 'sk_study',
    });
    expect(incompleteRows(state)).toEqual([]);
    expect(rowsOf(state, 'scene')[1]).toMatchObject({ action: 'link', cardId: 'sk_study' });
  });

  it('switching back to link keeps the card picked before', () => {
    let state = breakdownReducer(loaded(), {
      type: 'action',
      key: key('scene', '便利店'),
      action: 'skip',
    });
    state = breakdownReducer(state, {
      type: 'action',
      key: key('scene', '便利店'),
      action: 'link',
    });
    expect(rowsOf(state, 'scene')[0]).toMatchObject({ action: 'link', cardId: 'sk_store' });
  });

  it('skip all leaves nothing to apply', () => {
    let state = loaded();
    for (const kind of ['character', 'scene', 'prop'] as const) {
      state = breakdownReducer(state, { type: 'column', kind, action: 'skip' });
    }
    expect(nothingToApply(state)).toBe(true);
    expect(applyItems(state)).toEqual([]);
  });
});

describe('request builders', () => {
  it('sends each kind its own presets and only a link its card', () => {
    const items = applyItems(loaded());
    expect(items).toEqual([
      {
        kind: 'character',
        name: '林夏',
        action: 'create',
        card_id: null,
        description: '齐肩黑发',
        headings: [],
        age_stage: 'youth',
        period: null,
        lighting: null,
      },
      expect.objectContaining({ name: '顾沉', action: 'link', card_id: 'sk_gu' }),
      expect.objectContaining({
        name: '便利店',
        action: 'link',
        card_id: 'sk_store',
        headings: ['第一场', '第三场'],
        age_stage: null,
        period: 'contemporary',
        lighting: 'night_interior',
      }),
      expect.objectContaining({ name: '书房', action: 'create', headings: ['第二场'] }),
      expect.objectContaining({ kind: 'prop', name: '玉佩', lighting: null, period: null }),
    ]);
  });

  it('quotes one first image per new card, per kind', () => {
    const counts = createCounts(loaded());
    expect(counts).toEqual({ character: 1, scene: 1, prop: 1 });
    expect(quoteLines({ character: 2, scene: 0, prop: 1 }, 'cinematic')).toEqual([
      {
        operation: 'text_to_image',
        quality_tier: 'cinematic',
        duration_seconds: 0,
        asset_kind: 'character',
        character_views: null,
        count: 2,
      },
      expect.objectContaining({ asset_kind: 'prop', count: 1 }),
    ]);
  });
});
