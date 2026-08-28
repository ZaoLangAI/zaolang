/**
 * Splits a model's raw reasoning trace into paragraphs for display.
 *
 * The reasoning channel is free-form prose, not a schema the backend
 * controls — the only structure it reliably carries is whatever blank-line
 * breaks the model itself chose to lay its thinking out with. This leans on
 * those rather than parsing markdown syntax the model may or may not have
 * used, so a literal `##`/`**` in the raw text is left as-is rather than
 * rendered as a heading/bold run.
 *
 * Used for both a finished persisted trace and the live streaming preview
 * (`liveThinking`) — for the latter, this re-splits on every render as more
 * text arrives; a paragraph still being written just renders as its own
 * (growing) block, no different from a finished one.
 */
export function thinkingParagraphs(text: string): string[] {
  return text
    .split(/\n{2,}/)
    .map((paragraph) => paragraph.trim())
    .filter(Boolean);
}

/**
 * The most recent non-empty line of a (possibly still-streaming) reasoning
 * trace, split on single newlines — backs the collapsed "ticker" preview
 * that shows only the latest line instead of the full accumulating trace.
 *
 * Text arriving between two `\n`s is still "the current line" even while
 * it keeps growing (no newline has closed it yet), so this always reflects
 * whatever the model most recently wrote, one line at a time.
 */
export function latestThinkingLine(text: string): string {
  const lines = text.split('\n');
  for (let i = lines.length - 1; i >= 0; i -= 1) {
    const trimmed = lines[i]?.trim();
    if (trimmed) return trimmed;
  }
  return '';
}
