import type { AssetEntry, Character, GenerationJob } from '@/lib/api/types';
import { STUDIO_PROMPT_MAX_LENGTH } from '@/lib/prompt-limits';

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

/** Short layout hint written into the studio textarea so the author can
 * see (and edit) the sheet requirement. The backend still appends its own
 * `_CHARACTER_SHEET_LAYOUT_SUFFIX` on the front pass — this is the visible
 * half, not the only thing keeping the model on a multi-panel sheet. */
export const CHARACTER_SHEET_PROMPT_HINT =
  '生成一张角色设定图：左侧全身三视图（正面、侧面、背面），右侧面部特写、服装配饰细节与色板；纯白背景，同一人物，单张输出。';

const CHARACTER_LIBRARY_RETURN_TO = '/create/characters';

/** Identity + sheet-layout sentence for a library or script jump-out. */
export function characterSheetPrompt(input: { name: string; appearance?: string | null }): string {
  const name = input.name.trim();
  const appearance = input.appearance?.trim().replace(/[。．.]+$/, '') ?? '';
  const identity = appearance ? `${name}。${appearance}` : name;
  const prompt = identity
    ? `${identity}。${CHARACTER_SHEET_PROMPT_HINT}`
    : CHARACTER_SHEET_PROMPT_HINT;
  return prompt.slice(0, STUDIO_PROMPT_MAX_LENGTH);
}

/** Deep link into `ImageGenerationStudio` for a character-sheet job. */
export function characterImageStudioHref(input: {
  characterId: string;
  name: string;
  appearance?: string | null;
  returnTo?: string;
  /** File the sheet under this look (`target_variant_id`). */
  variantId?: string;
  /** Open on the identity portrait (定妆照) — identity text, no sheet layout. */
  portrait?: boolean;
}): string {
  const sheetPrompt = characterSheetPrompt({ name: input.name, appearance: input.appearance });
  const params = new URLSearchParams({
    mode: 'image_creation',
    assetKind: 'character',
    targetCharacterId: input.characterId,
    prompt: input.portrait
      ? sheetPrompt.replace(CHARACTER_SHEET_PROMPT_HINT, '').replace(/。$/, '')
      : sheetPrompt,
    subjectNameHint: input.name.trim().slice(0, 60),
    returnTo: input.returnTo ?? CHARACTER_LIBRARY_RETURN_TO,
  });
  if (input.variantId) params.set('targetVariantId', input.variantId);
  if (input.portrait) params.set('characterPortrait', '1');
  return `/create/new?${params.toString()}`;
}

/** The one image a character card shows now that the sheet replaced the
 * three-view grid — prefer an explicit front tag, else the first asset. */
export function characterSheetAsset(character: Character): CharacterReferenceAsset | undefined {
  return referenceByView(character, 'front') ?? character.reference_assets?.[0];
}

/**
 * Look up one tagged reference. Web no longer offers side/back completion,
 * but historical assets and `findCompletionJobFor` still key off view tags.
 */
export function referenceByView(
  character: Character,
  view: 'front' | 'side' | 'back',
): CharacterReferenceAsset | undefined {
  // The default (unnamed) look first: a labelled entry is another outfit's
  // sheet, kept alongside it (`characters.service.append_reference_asset`).
  const matches = character.reference_assets?.filter((asset) => asset.view === view) ?? [];
  return matches.find((asset) => !asset.label?.trim()) ?? matches[0];
}

/**
 * True once a front reference exists and either the side or back is still
 * missing. Web no longer offers completion; kept for tests and any
 * remaining API/iOS caller that still builds a side/back job.
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
    .filter(
      (candidate) => candidate.asset_kind === 'character' && !isCharacterCompletionJob(candidate),
    )
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

const SHEET_VIEWS = ['front', 'side', 'back'] as const;

/** `asset_variants.service._SHEET_ORDER`: a look's sheet, then its side and back views. */
const SHEET_ORDER: Record<string, number> = { front: 0, side: 1, back: 2 };

/**
 * What a job sends for this character when nothing was picked — mirrors
 * the backend's `asset_variants.service.default_subset` (no look named, no
 * shot hint): the card's anchor when it is an approved 定妆照 or the default
 * look's own image, then the default look's sheet and front/side/back
 * views, else its other non-expression images; at most three. Named
 * outfits and expression sheets only go in when picked
 * (`character_ref_selection`). Without `looks` (an older payload) it falls
 * back to the default look's unlabelled `reference_assets` views.
 */
export function defaultCharacterReferenceIds(character: Character): string[] {
  const looks = character.looks ?? [];
  if (looks.length === 0) return legacyDefaultReferenceIds(character);
  const isApproved = (entry: AssetEntry) => entry.status !== 'candidate';
  const defaultLook = looks.find((look) => look.is_default);
  const own = (defaultLook?.entries ?? []).filter(isApproved);
  const anchor = looks
    .flatMap((look) => look.entries ?? [])
    .find((entry) => entry.id === character.anchor_entry_id && isApproved(entry));
  const lead =
    anchor && (anchor.entry_type === 'identity_portrait' || own.includes(anchor)) ? [anchor] : [];
  const sheets = own
    .filter((entry) => entry.entry_type === 'character_sheet' || entry.entry_type === 'view')
    .sort(
      (a, b) =>
        (SHEET_ORDER[a.entry_type === 'character_sheet' ? 'front' : (a.view ?? '')] ?? 3) -
        (SHEET_ORDER[b.entry_type === 'character_sheet' ? 'front' : (b.view ?? '')] ?? 3),
    );
  const pool = sheets.length
    ? sheets
    : own.filter((entry) => entry.entry_type !== 'expression_sheet');
  let ordered = [...lead, ...pool];
  if (ordered.length === 0) {
    ordered = looks.flatMap((look) => look.entries ?? []).filter(isApproved);
  }
  return [...new Set(ordered.map((entry) => entry.asset_id))].slice(0, 3);
}

function legacyDefaultReferenceIds(character: Character): string[] {
  const entries = (character.reference_assets ?? []).filter((asset) => asset.asset_id);
  const sheet = SHEET_VIEWS.flatMap((view) =>
    entries.filter((asset) => asset.view === view && !asset.label?.trim()),
  );
  const unlabelled = entries.filter((asset) => !asset.label?.trim());
  const pool = sheet.length ? sheet : unlabelled.length ? unlabelled : entries;
  return pool.slice(0, 3).map((asset) => asset.asset_id);
}
