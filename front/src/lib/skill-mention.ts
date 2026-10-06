import type { CreationSkillCategory, CreationSkillSummary, Operation } from '@/lib/api/types';

import { getCaretCoordinates } from '@/lib/caret-position';

export const MENTION_MENU_WIDTH = 256;
export const MENTION_MENU_MAX_HEIGHT = 256;
export const MENTION_MENU_GAP = 6;

const IMAGE_ASSET_CATEGORIES = new Set<CreationSkillCategory>([
  'character',
  'scene_asset',
  'cover_asset',
  'prop_asset',
]);

/** The library card kinds a skill can be, and the creation entries (AC-8). */
export type AssetCreationKind = 'character' | 'scene' | 'prop';
export const ASSET_CREATION_KINDS: AssetCreationKind[] = ['character', 'scene', 'prop'];
const CARD_KIND_BY_CATEGORY: Partial<Record<CreationSkillCategory, AssetCreationKind>> = {
  character: 'character',
  scene_asset: 'scene',
  prop_asset: 'prop',
};
const LIBRARY_PATH: Record<AssetCreationKind, string> = {
  character: '/create/characters',
  scene: '/create/scenes',
  prop: '/create/props',
};
const REFERENCE_PARAM: Record<AssetCreationKind, string> = {
  character: 'referenceCharacterIds',
  scene: 'referenceSceneIds',
  prop: 'referencePropIds',
};

const IMAGE_OPERATIONS = new Set<Operation>(['text_to_image', 'image_to_image']);

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

/** The library card kind of an asset-card skill (character / scene / prop). */
export function skillCardKind(
  skill: Pick<CreationSkillSummary, 'category'>,
): AssetCreationKind | null {
  return CARD_KIND_BY_CATEGORY[skill.category] ?? null;
}

/**
 * A template whose declared operations are all image ones. There is no
 * image studio any more (AC-8): the plaza offers it as a style skill for
 * 角色 / 场景 / 道具创作 (`assetCreationHref`) instead.
 */
export function isImageOnlyTemplate(
  skill: Pick<CreationSkillSummary, 'category' | 'applicable_operations'>,
): boolean {
  if (skillCardKind(skill)) return false;
  const ops = skill.applicable_operations ?? [];
  return ops.length > 0 && ops.every((op) => IMAGE_OPERATIONS.has(op));
}

/** 用于{角色|场景|道具}创作: the library (the creation start) carries
 * `?skillId=` into a card's workspace, where the 创作 slot panel
 * preselects it as the style skill. */
export function assetCreationHref(kind: AssetCreationKind, skillId: string): string {
  return `${LIBRARY_PATH[kind]}?${new URLSearchParams({ skillId }).toString()}`;
}

/**
 * Every other plaza CTA lands in the video studio (`?skillId=` applies it
 * once there). An asset card the viewer owns rides along preselected as a
 * reference card — `character_ids` / `scene_ids` / `prop_ids` must be the
 * caller's own, so someone else's card is applied as a skill only.
 */
export function videoCreationHref(
  skill: Pick<CreationSkillSummary, 'id' | 'category' | 'author'>,
  viewerId?: string | null,
): string {
  const params = new URLSearchParams({ mode: 'video_creation', skillId: skill.id });
  const kind = skillCardKind(skill);
  // A character recipe maps onto `character_action` so the video studio
  // gets the right context.
  if (kind === 'character') params.set('videoAssetKind', 'character_action');
  if (kind && viewerId && skill.author?.user_id === viewerId) {
    params.set(REFERENCE_PARAM[kind], skill.id);
  }
  return `/create/new?${params.toString()}`;
}

export function filterMentionSkills(
  skills: CreationSkillSummary[],
  query: string,
): CreationSkillSummary[] {
  const needle = query.toLowerCase();
  if (!needle) return skills;
  return skills.filter((skill) => skill.title.toLowerCase().includes(needle));
}
