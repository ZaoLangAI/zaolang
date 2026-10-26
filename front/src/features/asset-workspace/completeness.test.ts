import { describe, expect, it } from 'vitest';

import type { AssetEntry, AssetVariant } from '@/lib/api/types';

import { cardCompleteness, orbitSource, slotStates } from './completeness';

function entry(id: string, patch: Partial<AssetEntry>): AssetEntry {
  return {
    id,
    asset_id: `a_${id}`,
    entry_type: 'other',
    status: 'approved',
    is_anchor: false,
    expressions: [],
    ...patch,
  } as AssetEntry;
}

function variant(entries: AssetEntry[], patch: Partial<AssetVariant> = {}): AssetVariant {
  return {
    id: 'v1',
    name: '默认造型',
    is_default: true,
    sort_order: 0,
    entries,
    ...patch,
  } as AssetVariant;
}

describe('slotStates', () => {
  it('maps a character look onto its slots', () => {
    const look = variant([
      entry('p', { entry_type: 'identity_portrait' }),
      entry('s', { entry_type: 'character_sheet' }),
      entry('x', { entry_type: 'expression_sheet', status: 'candidate' }),
    ]);
    const states = slotStates('character', look, look.entries ?? []);
    const byId = Object.fromEntries(states.map((s) => [s.slot.id, s.status]));
    expect(byId).toMatchObject({
      portrait: 'approved',
      sheet: 'approved',
      expressions: 'candidate',
    });
    // The turnaround poses are gone from a character's board.
    for (const id of ['front_figure', 'side', 'back', 'left', 'three_quarter']) {
      expect(byId).not.toHaveProperty(id);
    }
  });

  it('only shows the card-wide portrait on the default look', () => {
    const wedding = variant([], { id: 'v2', is_default: false });
    expect(slotStates('character', wedding, []).some((s) => s.slot.id === 'portrait')).toBe(false);
  });

  it('reads a scene reverse shot', () => {
    const plate = variant([
      entry('m', { entry_type: 'master' }),
      entry('r', { entry_type: 'shot', view: 'reverse' }),
    ]);
    const states = slotStates('scene', plate, plate.entries ?? []);
    expect(states.find((s) => s.slot.id === 'reverse')?.status).toBe('approved');
    expect(cardCompleteness('scene', [plate])).toEqual({ done: 2, total: 5 });
  });

  it('keeps the optional panorama slot apart from the master and its jobs', () => {
    const plate = variant([
      entry('m', { entry_type: 'master' }),
      entry('pano', { entry_type: 'panorama', status: 'candidate' }),
    ]);
    const states = slotStates('scene', plate, plate.entries ?? []);
    const panorama = states.find((s) => s.slot.id === 'panorama');
    expect(panorama?.status).toBe('candidate');
    expect(panorama?.slot.required).toBe(false);
    expect(states.find((s) => s.slot.id === 'master')?.approved?.id).toBe('m');
    // Optional: the badge still counts only the five required slots.
    expect(cardCompleteness('scene', [plate])).toEqual({ done: 1, total: 5 });

    const running = slotStates(
      'scene',
      variant([]),
      [],
      [{ job_id: 'j', status: 'running', mode: 'panorama', target_variant_id: 'v1' }],
    );
    expect(running.find((s) => s.slot.id === 'panorama')?.status).toBe('pending');
    expect(running.find((s) => s.slot.id === 'master')?.status).toBe('missing');
  });
});

describe('orbitSource', () => {
  it('prefers a front single figure over the sheet', () => {
    const sheet = entry('s', { entry_type: 'character_sheet' });
    const figure = entry('f', {
      entry_type: 'view',
      view: 'front',
      camera: { azimuth: 0, elevation: 0, distance: 'medium' },
    });
    expect(orbitSource('character', variant([sheet]))?.id).toBe('s');
    expect(orbitSource('character', variant([sheet, figure]))?.id).toBe('f');
    expect(orbitSource('scene', variant([entry('m', { entry_type: 'master' })]))?.id).toBe('m');
  });
});
