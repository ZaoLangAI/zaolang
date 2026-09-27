import { describe, expect, it } from 'vitest';

import { DRAFT_TITLE_MAX, draftDisplayTitle, titleFromPrompt } from './draft-title';

describe('titleFromPrompt', () => {
  it('takes the first non-empty line', () => {
    expect(titleFromPrompt('雨夜巷口摊牌\n第二行')).toBe('雨夜巷口摊牌');
  });

  it('rejects blank or non-string values', () => {
    expect(titleFromPrompt('   \n  ')).toBeNull();
    expect(titleFromPrompt(undefined)).toBeNull();
    expect(titleFromPrompt({ text: 'x' })).toBeNull();
  });

  it('caps at the draft title column', () => {
    const long = '画'.repeat(DRAFT_TITLE_MAX + 8);
    expect(titleFromPrompt(long)).toBe('画'.repeat(DRAFT_TITLE_MAX));
  });
});

describe('draftDisplayTitle', () => {
  it('prefers a stored title over the prompt', () => {
    expect(draftDisplayTitle({ title: '雾谷', params: { prompt: '另一句提示' } }, '未命名')).toBe(
      '雾谷',
    );
  });

  it('uses the prompt when the title was never set', () => {
    expect(draftDisplayTitle({ title: null, params: { prompt: '都市霓虹后巷' } }, '未命名')).toBe(
      '都市霓虹后巷',
    );
  });

  it('does not fall back to the section heading when both are missing', () => {
    expect(draftDisplayTitle({ title: '  ', params: {} }, '未命名')).toBe('未命名');
  });
});
