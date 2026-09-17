import { describe, expect, it } from 'vitest';

import {
  copyEditorSlot,
  recommendedCopyTemplateKey,
  templatesForCopyAgent,
} from './copy-routing';

const catalog = [
  { key: 'copy-suggest', slot: 'suggest', asset_kind: 'copy', prompt_template: 'SUGGEST' },
  { key: 'copy-enhance', slot: 'enhance', asset_kind: null, prompt_template: 'GENERIC' },
  {
    key: 'copy-enhance-character',
    slot: 'enhance',
    asset_kind: 'character',
    prompt_template: 'CHARACTER',
  },
  { key: 'copy-enhance-cover', slot: 'enhance', asset_kind: 'cover', prompt_template: 'COVER' },
  { key: 'copy-enhance-scene', slot: 'enhance', asset_kind: 'scene', prompt_template: 'SCENE' },
] as Parameters<typeof templatesForCopyAgent>[0];

describe('copyEditorSlot', () => {
  it('binds polish agents to enhance and the copy bucket to suggest', () => {
    expect(copyEditorSlot({ default_for_asset_kind: 'character' })).toBe('enhance');
    expect(copyEditorSlot({ default_for_asset_kind: 'scene' })).toBe('enhance');
    expect(copyEditorSlot({ default_for_asset_kind: 'cover' })).toBe('enhance');
    expect(copyEditorSlot({ default_for_asset_kind: 'copy' })).toBe('suggest');
    expect(copyEditorSlot({})).toBe('suggest');
  });
});

describe('recommendedCopyTemplateKey', () => {
  it('maps each request bucket to its dedicated starting prompt', () => {
    expect(recommendedCopyTemplateKey('character')).toBe('copy-enhance-character');
    expect(recommendedCopyTemplateKey('scene')).toBe('copy-enhance-scene');
    expect(recommendedCopyTemplateKey('cover')).toBe('copy-enhance-cover');
    expect(recommendedCopyTemplateKey('copy')).toBe('copy-suggest');
    expect(recommendedCopyTemplateKey(null)).toBe('');
  });
});

describe('templatesForCopyAgent', () => {
  it('offers only the dedicated enhance draft on a character/scene/cover agent', () => {
    expect(
      templatesForCopyAgent(catalog, 'enhance', 'character').map((template) => template.key),
    ).toEqual(['copy-enhance-character']);
    expect(
      templatesForCopyAgent(catalog, 'enhance', 'scene').map((template) => template.key),
    ).toEqual(['copy-enhance-scene']);
    expect(
      templatesForCopyAgent(catalog, 'enhance', 'cover').map((template) => template.key),
    ).toEqual(['copy-enhance-cover']);
  });

  it('offers only the work-copy draft on the copy bucket', () => {
    expect(templatesForCopyAgent(catalog, 'suggest', 'copy').map((template) => template.key)).toEqual(
      ['copy-suggest'],
    );
  });

  it('falls back to generic enhance when the bucket has no dedicated draft', () => {
    expect(
      templatesForCopyAgent(catalog, 'enhance', 'character_action').map((template) => template.key),
    ).toEqual(['copy-enhance']);
  });

  it('keeps the filled prompt body aligned with the dedicated key', () => {
    const [character] = templatesForCopyAgent(catalog, 'enhance', 'character');
    const [scene] = templatesForCopyAgent(catalog, 'enhance', 'scene');
    const [cover] = templatesForCopyAgent(catalog, 'enhance', 'cover');
    const [copy] = templatesForCopyAgent(catalog, 'suggest', 'copy');
    expect(character?.prompt_template).toBe('CHARACTER');
    expect(scene?.prompt_template).toBe('SCENE');
    expect(cover?.prompt_template).toBe('COVER');
    expect(copy?.prompt_template).toBe('SUGGEST');
  });
});
