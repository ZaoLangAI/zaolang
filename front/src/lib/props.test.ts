import { describe, expect, it } from 'vitest';

import type { AssetEntry, AssetVariant, Prop } from '@/lib/api/types';

import { defaultPropReferenceIds, propHeroAsset, propManageHref } from './props';

function entry(id: string, type: string, status = 'approved'): AssetEntry {
  return { id, asset_id: `ast_${id}`, entry_type: type, status } as AssetEntry;
}

function variant(id: string, entries: AssetEntry[], isDefault = false): AssetVariant {
  return { id, name: id, is_default: isDefault, entries } as AssetVariant;
}

describe('propManageHref', () => {
  it('links the workspace, optionally on one condition', () => {
    expect(propManageHref('skl_sword')).toBe('/create/props/skl_sword');
    expect(propManageHref('skl_sword', 'var_worn')).toBe('/create/props/skl_sword?look=var_worn');
  });

  it('encodes the ids', () => {
    expect(propManageHref('a/b', 'c d')).toBe('/create/props/a%2Fb?look=c%20d');
  });
});

describe('propHeroAsset', () => {
  it('prefers the hero plate, else the first image', () => {
    const prop = {
      reference_assets: [
        { asset_id: 'ast_view', view: 'side' },
        { asset_id: 'ast_hero', view: 'hero' },
      ],
    } as Prop;
    expect(propHeroAsset(prop)?.asset_id).toBe('ast_hero');
    expect(
      propHeroAsset({ reference_assets: [{ asset_id: 'ast_any', view: 'general' }] } as Prop)
        ?.asset_id,
    ).toBe('ast_any');
    expect(propHeroAsset({ reference_assets: [] } as unknown as Prop)).toBeUndefined();
  });
});

describe('defaultPropReferenceIds', () => {
  it("sends the default condition's hero plate first, at most two", () => {
    const prop = {
      anchor_entry_id: null,
      variants: [
        variant('worn', [entry('worn_master', 'master')]),
        variant(
          'main',
          [entry('side', 'view'), entry('master', 'master'), entry('detail', 'shot')],
          true,
        ),
      ],
    } as unknown as Prop;
    expect(defaultPropReferenceIds(prop)).toEqual(['ast_master', 'ast_side']);
  });

  it('skips candidates', () => {
    const prop = {
      variants: [
        variant('main', [entry('cand', 'master', 'candidate'), entry('view', 'view')], true),
      ],
    } as unknown as Prop;
    expect(defaultPropReferenceIds(prop)).toEqual(['ast_view']);
  });

  it("falls back to the card's anchor when the default condition is empty", () => {
    const prop = {
      anchor_entry_id: 'b',
      variants: [
        variant('main', [], true),
        variant('worn', [entry('a', 'shot'), entry('b', 'master')]),
      ],
    } as unknown as Prop;
    expect(defaultPropReferenceIds(prop)).toEqual(['ast_b']);
  });

  it('is empty for a card without images', () => {
    expect(defaultPropReferenceIds({ variants: [] } as unknown as Prop)).toEqual([]);
  });
});
