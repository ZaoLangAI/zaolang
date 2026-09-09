import type { Draft } from '@/lib/api/types';

/** Matches `Draft.title` (`String(200)`). First line of the prompt is enough
 * to tell two untitled cards apart; CSS `truncate` handles the rest. */
export const DRAFT_TITLE_MAX = 200;

/**
 * Working title for a generation draft that never got a real name.
 *
 * Studios only persist `title` for a remix (`source.work.title`). An original
 * create leaves it null, and the create-page rail used to fall back to the
 * section heading (`createPage.recentDrafts`) — every card then read
 * 「最近生成记录」. Prefer the stored title, then the first line of
 * `params.prompt` (already saved on create), then the caller's untitled copy.
 */
export function titleFromPrompt(prompt: unknown): string | null {
  if (typeof prompt !== 'string') return null;
  const line = prompt.trim().split('\n', 1)[0]?.trim() ?? '';
  if (!line) return null;
  return line.length > DRAFT_TITLE_MAX ? line.slice(0, DRAFT_TITLE_MAX) : line;
}

export function draftDisplayTitle(
  draft: Pick<Draft, 'title' | 'params'>,
  untitled: string,
): string {
  const titled = draft.title?.trim();
  if (titled) return titled;
  return titleFromPrompt(draft.params?.prompt) ?? untitled;
}
