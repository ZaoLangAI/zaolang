import { describe, expect, it } from 'vitest';

import type { ScriptDocument } from './api';
import { parseDialogueDirection, pendingDialogueLines } from './batch-plan';

describe('parseDialogueDirection', () => {
  it('strips a leading direction and maps a recognisable tone', () => {
    expect(parseDialogueDirection('（哽咽）你别走。')).toEqual({
      line: '你别走。',
      direction: '哽咽',
      emotion: 'sad',
    });
    expect(parseDialogueDirection('(怒吼) 滚出去！')).toEqual({
      line: '滚出去！',
      direction: '怒吼',
      emotion: 'angry',
    });
  });

  it('never reads a sneer as happy', () => {
    expect(parseDialogueDirection('（冷笑）你也配？')).toEqual({
      line: '你也配？',
      direction: '冷笑',
      emotion: null,
    });
  });

  it('leaves a plain line, or one that is only a parenthetical, whole', () => {
    expect(parseDialogueDirection('你好。')).toEqual({ line: '你好。', direction: null, emotion: null });
    expect(parseDialogueDirection('（沉默）')).toEqual({ line: '（沉默）', direction: null, emotion: null });
  });
});

describe('pendingDialogueLines', () => {
  it('speaks the line without its direction and prefers the block’s own emotion', () => {
    const document: ScriptDocument = {
      title: '',
      logline: '',
      characters: [],
      scenes: [
        {
          heading: '日·客厅',
          ref_id: null,
          blocks: [
            { type: 'dialogue', character: '林夏', text: '（笑）真的？' },
            { type: 'dialogue', character: '周屿', text: '（笑）假的。', emotion: 'calm' },
          ],
        },
      ],
    };
    expect(pendingDialogueLines(document).map((line) => [line.text, line.emotion])).toEqual([
      ['真的？', 'happy'],
      ['假的。', 'calm'],
    ]);
  });
});
