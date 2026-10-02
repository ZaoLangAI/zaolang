/**
 * Burned-in caption line layout. Pure — the caller supplies `measure`
 * (the compositor passes a canvas `measureText` at the matching font size) —
 * so the wrapping rules are testable without a 2D context.
 *
 * Rules, in order:
 * - CJK breaks between any two characters; Latin/digit runs break only
 *   between words.
 * - Closing punctuation never starts a line (it hangs one past the edge on
 *   the line before); an opening bracket never ends one (it moves down).
 * - At most `maxLines` lines. If the text needs more, the font shrinks in
 *   `FONT_SCALES` steps; if it still needs more at the smallest step, the
 *   last line is cut with "…" to fit.
 * - A `\n` is a hard break (the compositor joins simultaneous captions with
 *   it, so two captions stack instead of running together).
 */

export const FONT_SCALES = [1, 0.9, 0.8] as const;
export const ELLIPSIS = '…';

const NO_LINE_START = new Set([...'，。！？；：、）》」』】”’…—,.!?;:)]}']);
const NO_LINE_END = new Set([...'（《「『【“‘([{']);

export interface CaptionLayout {
  lines: string[];
  /** Multiplier on the caller's base font size the lines were laid out at. */
  fontScale: number;
  truncated: boolean;
}

/** Breakable units: one CJK/other character each, a Latin/digit word (with
 * its trailing spaces) as one unit, whitespace runs on their own. */
export function captionUnits(text: string): string[] {
  return Array.from(text.matchAll(/[A-Za-z0-9'’-]+[ \t]*|[ \t]+|./gsu), (match) => match[0]);
}

function startsWithNoLineStart(unit: string): boolean {
  return NO_LINE_START.has(unit.trimStart().charAt(0));
}

/** Greedy wrap of one paragraph into lines of units. */
function wrapUnits(
  units: string[],
  maxWidth: number,
  measure: (text: string) => number,
): string[][] {
  const lines: string[][] = [];
  let line: string[] = [];
  for (const unit of units) {
    const candidate = [...line, unit].join('').trimEnd();
    if (line.length === 0 || measure(candidate) <= maxWidth) {
      line.push(unit);
      continue;
    }
    if (startsWithNoLineStart(unit)) {
      // Hang closing punctuation on this line rather than start the next with it.
      line.push(unit);
      continue;
    }
    const carried: string[] = [];
    const last = line[line.length - 1] ?? '';
    if (line.length > 1 && NO_LINE_END.has(last.trimEnd().slice(-1))) {
      carried.push(line.pop() ?? '');
    }
    lines.push(line);
    line = [...carried, unit];
    if (line[0]?.trim() === '') line.shift();
  }
  if (line.join('').trim()) lines.push(line);
  return lines;
}

function wrapText(text: string, maxWidth: number, measure: (text: string) => number): string[][] {
  return text
    .split('\n')
    .map((paragraph) => paragraph.replace(/\s+/g, ' ').trim())
    .filter(Boolean)
    .flatMap((paragraph) => wrapUnits(captionUnits(paragraph), maxWidth, measure));
}

function ellipsize(text: string, maxWidth: number, measure: (text: string) => number): string {
  if (measure(text) <= maxWidth) return text;
  const chars = Array.from(text);
  let low = 0;
  let high = chars.length;
  while (low < high) {
    const mid = Math.ceil((low + high) / 2);
    if (measure(chars.slice(0, mid).join('').trimEnd() + ELLIPSIS) <= maxWidth) low = mid;
    else high = mid - 1;
  }
  return chars.slice(0, low).join('').trimEnd() + ELLIPSIS;
}

export function layoutCaptionLines(
  text: string,
  maxWidth: number,
  measure: (text: string, fontScale: number) => number,
  maxLines = 2,
): CaptionLayout {
  if (!text.trim()) return { lines: [], fontScale: 1, truncated: false };
  for (const scale of FONT_SCALES) {
    const lines = wrapText(text, maxWidth, (value) => measure(value, scale));
    if (lines.length <= maxLines) {
      return {
        lines: lines.map((units) => units.join('').trim()),
        fontScale: scale,
        truncated: false,
      };
    }
  }
  const scale = FONT_SCALES[FONT_SCALES.length - 1] ?? 1;
  const measureAtScale = (value: string) => measure(value, scale);
  const lines = wrapText(text, maxWidth, measureAtScale);
  const kept = lines.slice(0, maxLines - 1).map((units) => units.join('').trim());
  const rest = lines
    .slice(maxLines - 1)
    .map((units) => units.join(''))
    .join('')
    .trim();
  kept.push(ellipsize(rest, maxWidth, measureAtScale));
  return { lines: kept, fontScale: scale, truncated: true };
}
