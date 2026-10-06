import { describe, expect, it } from 'vitest';

import type { Scene } from '@/lib/api/types';

import { defaultSceneReferenceIds, sceneHeroAsset } from './scenes';

describe('sceneHeroAsset', () => {
  it('prefers the establishing-tagged asset, else the first one', () => {
    const scene = {
      reference_assets: [
        { asset_id: 'ast_detail', view: 'detail', url: 'https://cdn/detail.png' },
        { asset_id: 'ast_est', view: 'establishing', url: 'https://cdn/est.png' },
      ],
    } as Scene;
    expect(sceneHeroAsset(scene)?.asset_id).toBe('ast_est');
    expect(
      sceneHeroAsset({
        reference_assets: [{ asset_id: 'ast_any', view: 'general', url: 'https://cdn/any.png' }],
      } as Scene)?.asset_id,
    ).toBe('ast_any');
  });
});

describe('sceneHeroAsset with variants', () => {
  it('skips labelled variants when no establishing tag exists', () => {
    const scene = {
      reference_assets: [
        { asset_id: 'ast_dusk', view: 'general', label: '黄昏', url: 'https://cdn/dusk.png' },
        { asset_id: 'ast_master', view: 'general', label: null, url: 'https://cdn/m.png' },
      ],
    } as Scene;
    expect(sceneHeroAsset(scene)?.asset_id).toBe('ast_master');
  });
});

describe('defaultSceneReferenceIds', () => {
  it('sends the master plate and skips labelled variants', () => {
    const scene = {
      reference_assets: [
        { asset_id: 'dusk', view: 'general', label: '黄昏' },
        { asset_id: 'master', view: 'establishing', label: null },
        { asset_id: 'detail', view: 'detail', label: null },
        { asset_id: 'extra', view: 'general', label: null },
      ],
    } as Scene;
    expect(defaultSceneReferenceIds(scene)).toEqual(['master', 'detail']);
  });
});
