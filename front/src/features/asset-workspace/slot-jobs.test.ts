import { describe, expect, it } from 'vitest';

import type { AssetGraph, AssetVariant } from '@/lib/api/types';

import { KIND_CONFIG } from './kind-config';
import { slotJob } from './slot-jobs';

const graph = { card_id: 'sk_1', name: '林夏', description: '短发。' } as AssetGraph;
const look = {
  id: 'v2',
  name: '婚礼',
  description: '白色婚纱',
  is_default: false,
  presets: { prop_state: 'worn', lighting: 'dusk' },
} as unknown as AssetVariant;
const slot = (kind: keyof typeof KIND_CONFIG, id: string) =>
  KIND_CONFIG[kind].slots.find((s) => s.id === id)!;

describe('slotJob', () => {
  it('builds a portrait job on the card', () => {
    const job = slotJob('character', graph, look, slot('character', 'portrait'), {
      extra: '侧光',
      skillId: 'sk_style',
    });
    expect(job?.params).toMatchObject({
      prompt: '林夏。短发。白色婚纱。侧光',
      asset_kind: 'character',
      target_character_id: 'sk_1',
      character_portrait: true,
      skill_ids: ['sk_style'],
    });
    expect(job?.params.target_variant_id).toBeUndefined();
  });

  it('files a scene master into its variant with the variant presets', () => {
    const job = slotJob('scene', graph, look, slot('scene', 'master'));
    expect(job?.params).toMatchObject({
      asset_kind: 'scene',
      target_scene_id: 'sk_1',
      target_variant_id: 'v2',
      scene_lighting: 'dusk',
    });
  });

  it('carries a prop condition and leaves poses to the orbit route', () => {
    expect(slotJob('prop', graph, look, slot('prop', 'master'))?.params.prop_state).toBe('worn');
    expect(slotJob('prop', graph, look, slot('prop', 'side'))).toBeNull();
  });
});
