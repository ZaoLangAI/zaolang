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
      entry('side', { entry_type: 'view', view: 'side' }),
      entry('left', {
        entry_type: 'view',
        view: 'side',
        camera: { azimuth: 270, elevation: 0, distance: 'medium' },
        status: 'candidate',
      }),
    ]);
    const states = slotStates('character', look, look.entries ?? []);
    const byId = Object.fromEntries(states.map((s) => [s.slot.id, s.status]));
    expect(byId).toMatchObject({
      portrait: 'approved',
      sheet: 'approved',
      side: 'approved',
      left: 'candidate',
      back: 'missing',
      expressions: 'missing',
    });
  });

  it('marks pose slots pending while an orbit job runs', () => {
    const look = variant([entry('s', { entry_type: 'character_sheet' })]);
    const states = slotStates('character', look, look.entries ?? [], [
      { job_id: 'j', status: 'running', mode: 'orbit', target_variant_id: 'v1' },
    ]);
    expect(states.find((s) => s.slot.id === 'back')?.status).toBe('pending');
    expect(states.find((s) => s.slot.id === 'expressions')?.status).toBe('missing');
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
