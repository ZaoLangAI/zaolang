/**
 * Turns a script turn's raw streamed reply into what's safe to show a user
 * while it is still in flight.
 *
 * The model always replies with a short prose summary followed by a fenced
 * ```json block holding the *entire* script document (see the "Script
 * writing" section of `back/app/agents/copywriter.py`), and that JSON is
 * only ever parsed once the stream is fully drained — there is no
 * incremental parser on either side. Dumping the raw accumulating text
 * (summary + a growing, unparsable JSON fragment) into a chat bubble is
 * confusing and leaks an implementation detail, so this only ever returns
 * the prose part, plus a stable placeholder once the fence has started.
 */

const JSON_FENCE_MARKER = '```json';

// Chops off a fence marker that has only partially arrived (e.g. "```js"),
// so the tail end of the summary never flashes stray backticks for a beat
// before the rest of the marker streams in.
const PARTIAL_FENCE_TAIL = /`{1,3}(?:j(?:s(?:o(?:n)?)?)?)?$/;

/** `true` once the reply has started (or finished) writing the fenced script
 * body — the point past which nothing further should be shown verbatim. */
export function isWritingScriptBody(rawText: string): boolean {
  return rawText.includes(JSON_FENCE_MARKER);
}

/**
 * The prose summary only, safe to render at any point during the stream.
 * Once the JSON fence has started, this is already the complete summary
 * (the model writes it first) and stops changing — callers pair it with a
 * loading placeholder for the body via `isWritingScriptBody`.
 */
export function extractStreamingSummary(rawText: string): string {
  const fenceIndex = rawText.indexOf(JSON_FENCE_MARKER);
  const summary =
    fenceIndex === -1 ? rawText.replace(PARTIAL_FENCE_TAIL, '') : rawText.slice(0, fenceIndex);
  return summary.trim();
}

/**
 * A single string ready to render in a chat bubble: the prose summary, plus
 * `bodyPlaceholder` appended once the model has moved on to writing the
 * script body — never the raw JSON itself.
 */
export function streamingPreviewText(rawText: string, bodyPlaceholder: string): string {
  const summary = extractStreamingSummary(rawText);
  if (!isWritingScriptBody(rawText)) return summary;
  return summary ? `${summary}\n\n${bodyPlaceholder}` : bodyPlaceholder;
}
