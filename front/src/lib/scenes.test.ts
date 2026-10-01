import { describe, expect, it } from 'vitest';

import type { Scene } from '@/lib/api/types';

import { sceneHeroAsset, sceneImagePrompt, sceneImageStudioHref } from './scenes';

describe('sceneImagePrompt', () => {
  it('joins name and description', () => {
    expect(sceneImagePrompt({ name: '雨巷', description: '青石板路，纸伞' })).toBe(
      '雨巷。青石板路，纸伞',
    );
  });

  it('falls back to the name alone when there is no description', () => {
    expect(sceneImagePrompt({ name: '雨巷' })).toBe('雨巷');
  });

  it('does not stack a second period when description already ends with one', () => {
    expect(sceneImagePrompt({ name: '雨巷', description: '青石板路。' })).toBe('雨巷。青石板路');
  });
});

describe('sceneImageStudioHref', () => {
  it('targets the image studio with the scene query', () => {
    const href = sceneImageStudioHref({
      sceneId: 'skl_scene',
      name: '雨巷',
      description: '青石板路，纸伞',
    });
    const url = new URL(href, 'https://example.test');
    expect(url.pathname).toBe('/create/new');
    expect(url.searchParams.get('mode')).toBe('image_creation');
    expect(url.searchParams.get('assetKind')).toBe('scene');
    expect(url.searchParams.get('targetSceneId')).toBe('skl_scene');
    expect(url.searchParams.get('subjectNameHint')).toBe('雨巷');
    expect(url.searchParams.get('returnTo')).toBe('/create/scenes');
    expect(url.searchParams.get('prompt')).toBe('雨巷。青石板路，纸伞');
  });
});

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
