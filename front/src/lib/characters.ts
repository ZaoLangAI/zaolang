import type { Character, GenerationJob } from '@/lib/api/types';

type CharacterReferenceAsset = NonNullable<Character['reference_assets']>[number];

/**
 * The `prompt` sent with a "补全侧面/背面" completion job — never shown to
 * the user (`GenerationVersionHistory` filters completion jobs out of the
 * version list entirely) and never actually used by the planner either:
 * `execute_asset_planning` (`back/app/workflows/nodes.py`) hard-overrides
 * each pass's intent with its own fixed, per-view instruction (`_CHARACTER_
 * COMPLETION_FIXED_PROMPTS`) regardless of what a caller sends here — this
 * one shared string covers a `views` request of just `['side']`, just
 * `['back']`, or both at once. This exists purely to satisfy
 * `GenerationParams.prompt`'s non-empty validation with something
 * self-explanatory, instead of (as before the backend fix) a character's
 * own name/description, which could contradict the attached front
 * reference image. Written as "侧面图和背面图" rather than the backend's old
 * ambiguous "侧面/背面图" slash — this string only ever surfaces in job-
 * history/debugging views where a human reads it standalone, so it should
 * read clearly on its own even though it plays no role in what actually
 * gets generated.
 */
export const CHARACTER_COMPLETION_PROMPT = '参考本图生成侧面图和背面图';

/**
 * Shared "does this character still need its side/back view?" logic —
 * used both by `CharacterLibrary`'s "补全侧面/背面" card action and by
 * `ImageGenerationStudio`'s inline result, which offers the same completion
 * step right after a character's front view finishes generating instead of
 * making the user jump to the character library page for it.
 */
export function referenceByView(
  character: Character,
  view: 'front' | 'side' | 'back',
): CharacterReferenceAsset | undefined {
  return character.reference_assets?.find((asset) => asset.view === view);
}

/**
 * True once a front reference exists and either the side or back is still
 * missing — the same guard `CharacterLibrary`'s completion button and the
 * studio's inline result button both need before offering "补全侧面/背面".
 */
export function canCompleteViews(character: Character): boolean {
  return (
    Boolean(referenceByView(character, 'front')) &&
    (!referenceByView(character, 'side') || !referenceByView(character, 'back'))
  );
}

/**
 * Which of `side`/`back` a completion job should actually request — never
 * a view the character already has a reference for. Submitting the missing
 * subset (instead of always hardcoding `['side', 'back']`) is what lets a
 * user delete just one unsatisfying view and regenerate only that one
 * without a fresh request silently overwriting the other, already-approved
 * view.
 *
 * Empty when there's no front reference yet — mirrors `canCompleteViews`'s
 * own guard, since a completion job always needs the front view as its
 * material.
 */
export function missingReferenceViews(character: Character): Array<'side' | 'back'> {
  if (!referenceByView(character, 'front')) return [];
  return (['side', 'back'] as const).filter((view) => !referenceByView(character, view));
}

/**
 * A "补全侧面/背面" completion job — `asset_kind: 'character'` with
 * `character_views` set and *not* including `'front'` (e.g. `['side',
 * 'back']`). Purely data-derived (no character-record lookup needed), so it
 * identifies a completion job the same way whether it was just submitted
 * this session or read back from the draft's job list after a reload.
 *
 * `GenerationVersionHistory` filters these out entirely — a completion job
 * supplements whichever front-view version it was submitted for (see
 * `findCompletionJobFor` below) rather than counting as a version of its
 * own.
 */
export function isCharacterCompletionJob(job: GenerationJob): boolean {
  return (
    job.asset_kind === 'character' &&
    Boolean(job.character_views?.length) &&
    !(job.character_views ?? []).includes('front')
  );
}

/** Failed / cancelled / expired completions do not supplement a front
 * view — they would hide the "补全侧面/背面" button and leave no in-session
 * way to try again. Matches `findCompletionJobFor`'s docstring. */
const TERMINAL_FAILURE_STATUSES = new Set(['failed', 'cancelled', 'expired']);

/**
 * Which succeeded (or still in-flight) completion job, if any, supplements
 * `job` — the one nearest to it chronologically, for the same linked
 * character, and before whichever *other* front-view job comes next (so
 * regenerating the front view more than once and completing only the
 * latest one doesn't mis-attribute that completion to an older front job).
 *
 * `jobs` is expected to be every job known under the same draft (see
 * `ImageGenerationStudio`'s `knownJobsById`) — this is a pure lookup over
 * that list, not a fetch of its own.
 */
export function findCompletionJobFor(
  jobs: GenerationJob[],
  job: GenerationJob,
): GenerationJob | null {
  if (job.asset_kind !== 'character' || isCharacterCompletionJob(job)) return null;
  const targetCharacterId = job.linked_character_id;
  if (!targetCharacterId) return null;

  const frontJobs = jobs
    .filter((candidate) => candidate.asset_kind === 'character' && !isCharacterCompletionJob(candidate))
    .sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime());
  const index = frontJobs.findIndex((candidate) => candidate.id === job.id);
  if (index === -1) return null;

  const windowStart = new Date(job.created_at).getTime();
  const next = frontJobs[index + 1];
  const windowEnd = next ? new Date(next.created_at).getTime() : Infinity;

  const completions = jobs
    .filter((candidate) => isCharacterCompletionJob(candidate))
    .filter((candidate) => candidate.linked_character_id === targetCharacterId)
    .filter((candidate) => !TERMINAL_FAILURE_STATUSES.has(candidate.status))
    .filter((candidate) => {
      const at = new Date(candidate.created_at).getTime();
      return at >= windowStart && at < windowEnd;
    })
    .sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime());

  return completions[completions.length - 1] ?? null;
}
