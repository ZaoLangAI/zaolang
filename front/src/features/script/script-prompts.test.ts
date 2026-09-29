import { describe, expect, it } from 'vitest';

import { CHARACTER_SHEET_PROMPT_HINT } from '@/lib/characters';

import type { ScriptCharacter, ScriptDocument, ScriptScene } from './api';
import {
  DEFAULT_CHARACTER_MEDIUM,
  applySegmentBlockTexts,
  breakpointSegmentPrompt,
  breakpointSegmentUserPrompt,
  characterAppearanceWithMedium,
  characterImagePrompt,
  composeClipPrompt,
  displaySegmentBlocks,
  episodeLinkedAssetIds,
  promptForBreakpointKey,
} from './script-prompts';

function character(overrides: Partial<ScriptCharacter> = {}): ScriptCharacter {
  return { name: '林夏', traits: '', character_ref_id: null, ...overrides };
}

describe('characterAppearanceWithMedium', () => {
  it('prepends the photoreal default when traits name no medium', () => {
    expect(characterAppearanceWithMedium('年轻女性，齐肩黑发')).toBe(
      `${DEFAULT_CHARACTER_MEDIUM}，年轻女性，齐肩黑发`,
    );
  });

  it('uses the photoreal default alone when traits are empty', () => {
    expect(characterAppearanceWithMedium('')).toBe(DEFAULT_CHARACTER_MEDIUM);
    expect(characterAppearanceWithMedium('   ')).toBe(DEFAULT_CHARACTER_MEDIUM);
  });

  it('leaves an explicit photoreal or anime medium unchanged', () => {
    expect(characterAppearanceWithMedium('真人写实影视短剧造型，西装男性')).toBe(
      '真人写实影视短剧造型，西装男性',
    );
    expect(characterAppearanceWithMedium('二维日系动漫造型，银发高中生')).toBe(
      '二维日系动漫造型，银发高中生',
    );
  });
});

describe('characterImagePrompt', () => {
  it('seeds the sheet prompt with the default medium for bare traits', () => {
    expect(characterImagePrompt(character({ traits: '年轻女性，齐肩黑发' }))).toBe(
      `林夏。${DEFAULT_CHARACTER_MEDIUM}，年轻女性，齐肩黑发。${CHARACTER_SHEET_PROMPT_HINT}`,
    );
  });

  it('does not prepend a second medium when traits already name one', () => {
    expect(characterImagePrompt(character({ traits: '二维日系动漫造型，银发高中生' }))).toBe(
      `林夏。二维日系动漫造型，银发高中生。${CHARACTER_SHEET_PROMPT_HINT}`,
    );
  });
});

const mixedScene = (): ScriptScene => ({
  heading: '雨巷',
  ref_id: 'sk_scene',
  blocks: [
    { type: 'scene', character: null, text: '夜，霓虹倒映积水' },
    { type: 'action', character: null, text: '苏晴撑伞停下' },
    { type: 'camera', character: null, text: '中景推近' },
    { type: 'dialogue', character: '苏晴', text: '你终于来了。' },
    { type: 'action', character: null, text: '她转身离开' },
    { type: 'breakpoint', character: null, text: '切' },
    { type: 'dialogue', character: '林夏', text: '别走。' },
  ],
});

describe('breakpointSegmentPrompt', () => {
  it('keeps action and dialogue in document order, not grouped by type', () => {
    const prompt = breakpointSegmentPrompt(mixedScene(), 5);
    expect(prompt).toBe(
      [
        '雨巷，夜，霓虹倒映积水',
        '动作：苏晴撑伞停下',
        '镜头：中景推近',
        '台词：苏晴：你终于来了。',
        '动作：她转身离开',
      ].join('\n'),
    );
  });

  it('inherits this scene’s environment on a later segment with no scene block', () => {
    expect(breakpointSegmentPrompt(mixedScene(), 7)).toBe(
      '雨巷，夜，霓虹倒映积水\n台词：林夏：别走。',
    );
  });
});

describe('breakpointSegmentUserPrompt / promptForBreakpointKey', () => {
  it('seeds the clip studio with original wording, speaker included', () => {
    expect(breakpointSegmentUserPrompt(mixedScene(), 5)).toBe(
      [
        '雨巷',
        '夜，霓虹倒映积水',
        '苏晴撑伞停下',
        '中景推近',
        '苏晴：你终于来了。',
        '她转身离开',
      ].join('\n'),
    );
  });

  it('resolves a key to that segment only', () => {
    const document: ScriptDocument = {
      title: '',
      logline: '',
      characters: [],
      scenes: [mixedScene()],
    };
    expect(promptForBreakpointKey(document, '雨巷#0')).toContain('你终于来了');
    expect(promptForBreakpointKey(document, '雨巷#0')).not.toContain('别走');
    expect(promptForBreakpointKey(document, '雨巷#1')).toContain('别走');
    expect(promptForBreakpointKey(document, '不存在#0')).toBeNull();
  });
});

describe('displaySegmentBlocks / applySegmentBlockTexts', () => {
  it('surfaces inherited environment separately from segment-owned blocks', () => {
    const shown = displaySegmentBlocks(mixedScene(), 7);
    expect(shown.environment.map((block) => block.text)).toEqual(['夜，霓虹倒映积水']);
    expect(shown.blocks.map((block) => block.text)).toEqual(['别走。']);
  });

  it('writes polished texts back onto the matching segment only', () => {
    const document: ScriptDocument = {
      title: '',
      logline: '',
      characters: [],
      scenes: [mixedScene()],
    };
    const next = applySegmentBlockTexts(document, '雨巷#1', [
      { type: 'dialogue', character: '林夏', text: '别走啊。' },
    ]);
    expect(next?.scenes[0]?.blocks[6]?.text).toBe('别走啊。');
    expect(next?.scenes[0]?.blocks[3]?.text).toBe('你终于来了。');
  });

  it('rejects a polish that changes block count or types', () => {
    const document: ScriptDocument = {
      title: '',
      logline: '',
      characters: [],
      scenes: [mixedScene()],
    };
    expect(
      applySegmentBlockTexts(document, '雨巷#1', [{ type: 'action', character: null, text: '错' }]),
    ).toBeNull();
  });
});

describe('episodeLinkedAssetIds', () => {
  it('collects only this episode’s already-linked character and scene cards', () => {
    const document: ScriptDocument = {
      title: '',
      logline: '',
      characters: [
        { name: '苏晴', traits: '', character_ref_id: 'sk_su' },
        { name: '路人', traits: '', character_ref_id: null },
      ],
      scenes: [
        { heading: '雨巷', ref_id: 'sk_alley', blocks: [] },
        { heading: '未关联', ref_id: null, blocks: [] },
      ],
    };
    expect(episodeLinkedAssetIds(document)).toEqual({
      characterIds: ['sk_su'],
      sceneIds: ['sk_alley'],
    });
  });
});

describe('composeClipPrompt', () => {
  it('joins the user prompt and the labeled segment', () => {
    expect(composeClipPrompt('雨巷\n苏晴撑伞', '动作：苏晴撑伞')).toBe(
      '雨巷\n苏晴撑伞\n\n动作：苏晴撑伞',
    );
  });
});
