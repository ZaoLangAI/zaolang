import type { CreationSkillCategory, CreationSkillSummary, Operation } from '@/lib/api/types';

import { getCaretCoordinates } from '@/lib/caret-position';

export const MENTION_MENU_WIDTH = 256;
export const MENTION_MENU_MAX_HEIGHT = 256;
export const MENTION_MENU_GAP = 6;

const IMAGE_ASSET_CATEGORIES = new Set<CreationSkillCategory>([
  'character',
  'scene_asset',
  'cover_asset',
]);

const IMAGE_OPERATIONS = new Set<Operation>(['text_to_image', 'image_to_image']);
const VIDEO_OPERATIONS = new Set<Operation>(['text_to_video', 'image_to_video', 'video_to_video']);

export function escapeForRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/** A skill's `@Title` marker, bounded by whitespace/start and whitespace/end so it can't false-match inside an unrelated longer word. */
export function mentionTokenPattern(title: string): RegExp {
  return new RegExp(`(?:^|\\s)@${escapeForRegExp(title)}(?=\\s|$)`);
}

export function hasMentionToken(text: string, title: string): boolean {
  return mentionTokenPattern(title).test(text);
}

/** Removes one `@Title` token (plus the single trailing space inserted with it) without disturbing the whitespace before it. */
export function stripMentionToken(text: string, title: string): string {
  const pattern = new RegExp(`@${escapeForRegExp(title)}(?=\\s|$)`);
  const match = pattern.exec(text);
  if (!match) return text;
  const end = match.index + match[0].length;
  const hasTrailingSpace = text[end] === ' ';
  return text.slice(0, match.index) + text.slice(hasTrailingSpace ? end + 1 : end);
}

/** Finds an in-progress `@query` right before the caret, requiring the `@` itself to sit at the start of the text or right after whitespace. */
export function detectMentionTrigger(
  value: string,
  caret: number,
): { start: number; query: string } | null {
  const before = value.slice(0, caret);
  const match = /@([^\s@]*)$/.exec(before);
  if (!match) return null;
  const atIndex = match.index;
  const charBefore = atIndex === 0 ? '' : (before[atIndex - 1] ?? '');
  if (atIndex !== 0 && !/\s/.test(charBefore)) return null;
  return { start: atIndex, query: match[1] ?? '' };
}

export function computeMentionMenuStyle(
  textarea: HTMLTextAreaElement,
  container: HTMLElement,
  caretIndex: number,
): React.CSSProperties {
  const caret = getCaretCoordinates(textarea, caretIndex);
  const anchorTop = textarea.offsetTop + caret.top;
  const anchorLeft = textarea.offsetLeft + caret.left;
  const containerRect = container.getBoundingClientRect();
  const spaceBelow = window.innerHeight - (containerRect.top + anchorTop + caret.height);
  const openUpward =
    spaceBelow < MENTION_MENU_MAX_HEIGHT && containerRect.top + anchorTop > MENTION_MENU_MAX_HEIGHT;
  const maxLeft = Math.max(container.clientWidth - MENTION_MENU_WIDTH - 4, 4);
  return {
    left: Math.min(Math.max(anchorLeft, 4), maxLeft),
    top: openUpward
      ? anchorTop - MENTION_MENU_MAX_HEIGHT - MENTION_MENU_GAP
      : anchorTop + caret.height + MENTION_MENU_GAP,
  };
}

/** Empty `applicable_operations` means the template is built for any operation. */
export function isSkillApplicableToOperation(
  skill: Pick<CreationSkillSummary, 'applicable_operations'>,
  operation: Operation,
): boolean {
  const ops = skill.applicable_operations;
  return !ops || ops.length === 0 || ops.includes(operation);
}

/** Free, or already purchased / owned. Locked paid skills stay out of the studio `@` list. */
export function isSkillUsableForMention(
  skill: Pick<CreationSkillSummary, 'access_credits' | 'viewer_unlocked'>,
): boolean {
  return skill.access_credits === 0 || skill.viewer_unlocked;
}

export function isSkillMentionable(skill: CreationSkillSummary, operation: Operation): boolean {
  if (IMAGE_ASSET_CATEGORIES.has(skill.category)) {
    const ops = skill.applicable_operations;
    // User-authored roster skills usually declare no operations (empty =
    // "any" for templates). Those must stay out of `@` / `skill_ids` and
    // keep going through the dedicated character/scene roster instead.
    if (!ops || ops.length === 0 || !ops.includes(operation)) return false;
    return isSkillUsableForMention(skill);
  }
  return isSkillApplicableToOperation(skill, operation) && isSkillUsableForMention(skill);
}

/** Plaza / `@` apply lands in the image studio when the skill is image-only. */
export function creationStudioHref(
  skill: Pick<CreationSkillSummary, 'id' | 'category' | 'applicable_operations'>,
): string {
  const ops = skill.applicable_operations ?? [];
  const hasImage = ops.some((op) => IMAGE_OPERATIONS.has(op));
  const hasVideo = ops.some((op) => VIDEO_OPERATIONS.has(op));
  const mode = hasImage && !hasVideo ? 'image_creation' : 'video_creation';
  const params = new URLSearchParams({ mode, skillId: skill.id });
  if (skill.category === 'character') {
    params.set('assetKind', 'character');
    // Video has no `scene`/`cover` asset-kind equivalent, but a character
    // recipe maps onto `character_action` so the video studio still gets
    // the right context when `mode` resolves to `video_creation`.
    if (mode === 'video_creation') params.set('videoAssetKind', 'character_action');
  } else if (skill.category === 'scene_asset') {
    params.set('assetKind', 'scene');
  } else if (skill.category === 'cover_asset') {
    params.set('assetKind', 'cover');
  }
  return `/create/new?${params.toString()}`;
}

/** The still an image-asset recipe should hang on the image studio's
 * reference rail: the card's anchor (`anchor_asset_id` on the skill
 * detail), else a legacy nested `reference_assets` entry (older API), else
 * the cover. */
export function firstSkillReferenceAssetId(
  params: Record<string, unknown>,
  coverAssetId?: string | null,
  anchorAssetId?: string | null,
): string | undefined {
  if (anchorAssetId) return anchorAssetId;
  for (const nestKey of ['character', 'scene'] as const) {
    const bundle = params[nestKey];
    if (!bundle || typeof bundle !== 'object' || Array.isArray(bundle)) continue;
    const refs = (bundle as { reference_assets?: unknown }).reference_assets;
    if (!Array.isArray(refs)) continue;
    for (const ref of refs) {
      if (!ref || typeof ref !== 'object' || Array.isArray(ref)) continue;
      const assetId = (ref as { asset_id?: unknown }).asset_id;
      if (typeof assetId === 'string' && assetId) return assetId;
    }
  }
  return coverAssetId || undefined;
}

export function filterMentionSkills(
  skills: CreationSkillSummary[],
  query: string,
): CreationSkillSummary[] {
  const needle = query.toLowerCase();
  if (!needle) return skills;
  return skills.filter((skill) => skill.title.toLowerCase().includes(needle));
}
