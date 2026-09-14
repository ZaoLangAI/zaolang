import { describe, expect, it } from 'vitest';

import { ELLIPSIS, FONT_SCALES, layoutCaptionLines } from './caption-layout';

// Every character is 10px wide at scale 1 — enough to reason about exact breaks.
const measure = (text: string, scale: number) => Array.from(text).length * 10 * scale;

describe('layoutCaptionLines', () => {
  it('keeps a short caption on one line at full size', () => {
    expect(layoutCaptionLines('你好', 200, measure)).toEqual({
      lines: ['你好'],
      fontScale: 1,
      truncated: false,
    });
  });

  it('wraps CJK between characters within the width', () => {
    const layout = layoutCaptionLines('一二三四五六七八九十一二', 100, measure);
    expect(layout.lines).toEqual(['一二三四五六七八九十', '一二']);
    expect(layout.truncated).toBe(false);
  });

  it('never starts a line with closing punctuation — it hangs on the line before', () => {
    const layout = layoutCaptionLines('一二三四五六七八九十。一二', 100, measure);
    expect(layout.lines[0]).toBe('一二三四五六七八九十。');
    expect(layout.lines[1]?.startsWith('。')).toBe(false);
  });

  it('never ends a line with an opening bracket — it moves down', () => {
    const layout = layoutCaptionLines('一二三四五六七八九「十一」', 100, measure);
    expect(layout.lines[0]?.endsWith('「')).toBe(false);
    expect(layout.lines[1]?.startsWith('「')).toBe(true);
  });

  it('breaks Latin text only between words', () => {
    // "hello there" is exactly 110px, so it fits; "world" moves down whole.
    const layout = layoutCaptionLines('hello there world', 110, measure);
    expect(layout.lines).toEqual(['hello there', 'world']);
    for (const line of layout.lines) expect(line).toMatch(/^[a-z]+( [a-z]+)*$/);
    expect(layout.lines.join(' ')).toBe('hello there world');
  });

  it('shrinks the font before truncating', () => {
    // 22 chars: 3 lines at 100px/scale 1, fits in 2 lines once shrunk.
    const layout = layoutCaptionLines('一'.repeat(22), 100, measure);
    expect(layout.lines).toHaveLength(2);
    expect(layout.fontScale).toBeLessThan(1);
    expect(layout.truncated).toBe(false);
  });

  it('truncates with an ellipsis at the smallest size, still inside the width', () => {
    const smallest = FONT_SCALES[FONT_SCALES.length - 1] ?? 1;
    const layout = layoutCaptionLines('一'.repeat(80), 100, measure);
    expect(layout.truncated).toBe(true);
    expect(layout.fontScale).toBe(smallest);
    expect(layout.lines).toHaveLength(2);
    expect(layout.lines[1]?.endsWith(ELLIPSIS)).toBe(true);
    for (const line of layout.lines) expect(measure(line, smallest)).toBeLessThanOrEqual(100);
  });

  it('treats a newline as a hard break so simultaneous captions stack', () => {
    expect(layoutCaptionLines('第一句\n第二句', 200, measure).lines).toEqual(['第一句', '第二句']);
  });

  it('returns nothing for a blank caption', () => {
    expect(layoutCaptionLines('   ', 200, measure).lines).toEqual([]);
  });
});
