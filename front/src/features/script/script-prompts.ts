import { characterSheetPrompt } from '@/lib/characters';
import { STUDIO_PROMPT_MAX_LENGTH } from '@/lib/prompt-limits';

import type { ScriptBlock, ScriptCharacter, ScriptDocument, ScriptScene } from './api';
import { breakpointSegmentBlocks, locateBreakpoint } from './script-breakpoint';

/** Default visual medium prepended when a script character's traits name none.
 * Must stay aligned with `nodes._CHARACTER_PHOTOREAL_MEDIUM`. */
export const DEFAULT_CHARACTER_MEDIUM = '真人写实影视短剧造型';

const PHOTOREAL_MEDIUM_MARKERS = ['真人', '写实', '影视', 'photoreal'] as const;
const ANIME_MEDIUM_MARKERS = ['动漫', '二次元', 'anime', '插画'] as const;

function hasVisualMedium(text: string): boolean {
  const lowered = text.toLowerCase();
  return [...PHOTOREAL_MEDIUM_MARKERS, ...ANIME_MEDIUM_MARKERS].some((marker) =>
    lowered.includes(marker.toLowerCase()),
  );
}

/** Seed appearance for a character sheet: keep an explicit medium, else
 * lock the script-studio default so one cast member cannot go photoreal
 * while the next goes anime. */
export function characterAppearanceWithMedium(appearance: string): string {
  const trimmed = appearance.trim();
  if (hasVisualMedium(trimmed)) return trimmed;
  return trimmed ? `${DEFAULT_CHARACTER_MEDIUM}，${trimmed}` : DEFAULT_CHARACTER_MEDIUM;
}

/** Seed prompt for a character's sheet jump-out or in-page batch job. */
export function characterImagePrompt(character: ScriptCharacter): string {
  return characterSheetPrompt({
    name: character.name,
    appearance: characterAppearanceWithMedium(character.traits),
  });
}

/** Seed prompt for a scene's auto-created/updated image: heading plus every
 * non-empty `scene` block, never an `action` (those describe people). */
export function sceneImagePrompt(scene: ScriptScene): string {
  const envTexts = scene.blocks
    .filter((block) => block.type === 'scene' && block.text.trim())
    .map((block) => block.text.trim());
  return envTexts.length ? `${scene.heading}，${envTexts.join('，')}` : scene.heading;
}

/** Linked character/scene ids a breakpoint segment can hand to video generation. */
export function resolveBreakpointRefs(
  document: ScriptDocument,
  scene: ScriptScene,
  breakpointBlockIndex: number,
): {
  characterIds: string[];
  sceneId: string | null;
  /** Linked looks (`character_id → look id`) — only non-default ones. */
  characterLooks: Record<string, string>;
  sceneVariantId: string | null;
} {
  const names = new Set(
    breakpointSegmentBlocks(scene, breakpointBlockIndex)
      .filter((block) => block.type === 'dialogue' && block.character)
      .map((block) => block.character as string),
  );
  const linked = document.characters.filter(
    (character) => names.has(character.name) && character.character_ref_id,
  );
  const characterLooks: Record<string, string> = {};
  for (const character of linked) {
    if (character.look_id) characterLooks[character.character_ref_id as string] = character.look_id;
  }
  return {
    characterIds: linked.map((character) => character.character_ref_id as string),
    sceneId: scene.ref_id,
    characterLooks,
    sceneVariantId: scene.ref_id ? (scene.variant_id ?? null) : null,
  };
}

/** `*_ref_selection` items for a segment's linked looks / scene variant. */
export function lookSelections(refs: {
  characterLooks: Record<string, string>;
  sceneId: string | null;
  sceneVariantId: string | null;
}): {
  character_ref_selection: { character_id: string; variant_id: string }[] | null;
  scene_ref_selection: { scene_id: string; variant_id: string }[] | null;
} {
  const characters = Object.entries(refs.characterLooks).map(([character_id, variant_id]) => ({
    character_id,
    variant_id,
  }));
  return {
    character_ref_selection: characters.length ? characters : null,
    scene_ref_selection:
      refs.sceneId && refs.sceneVariantId
        ? [{ scene_id: refs.sceneId, variant_id: refs.sceneVariantId }]
        : null,
  };
}

function shootableSegmentBlocks(scene: ScriptScene, breakpointBlockIndex: number): ScriptBlock[] {
  return breakpointSegmentBlocks(scene, breakpointBlockIndex).filter(
    (block) => block.type !== 'breakpoint' && block.text.trim(),
  );
}

export function sceneEnvironmentBlocks(scene: ScriptScene): ScriptBlock[] {
  return scene.blocks.filter((block) => block.type === 'scene' && block.text.trim());
}

function formatLabeledBlock(block: ScriptBlock): string {
  const text = block.text.trim();
  if (!text) return '';
  if (block.type === 'action') return `动作：${text}`;
  if (block.type === 'camera') return `镜头：${text}`;
  if (block.type === 'dialogue') {
    return block.character ? `台词：${block.character}：${text}` : `台词：${text}`;
  }
  return text;
}

function formatUserBlock(block: ScriptBlock): string {
  const text = block.text.trim();
  if (!text) return '';
  if (block.type === 'dialogue' && block.character) return `${block.character}：${text}`;
  return text;
}

/** Scene heading plus establishing `scene` lines, for a later segment that
 * no longer contains those blocks itself. */
export function sceneEnvironmentPrefix(scene: ScriptScene): string {
  const env = sceneEnvironmentBlocks(scene).map((block) => block.text.trim());
  return env.length ? `${scene.heading}，${env.join('，')}` : scene.heading;
}

/**
 * Labeled, document-order copy for a generation job (batch or compose).
 * Later segments inherit this scene's environment when they have no `scene`
 * block of their own.
 */
export function breakpointSegmentPrompt(scene: ScriptScene, breakpointBlockIndex: number): string {
  const blocks = shootableSegmentBlocks(scene, breakpointBlockIndex);
  const hasScene = blocks.some((block) => block.type === 'scene');
  const lines: string[] = [];
  if (hasScene) {
    const env = blocks.filter((block) => block.type === 'scene').map((block) => block.text.trim());
    lines.push(`${scene.heading}，${env.join('，')}`);
    for (const block of blocks) {
      if (block.type === 'scene') continue;
      const line = formatLabeledBlock(block);
      if (line) lines.push(line);
    }
  } else {
    lines.push(sceneEnvironmentPrefix(scene));
    for (const block of blocks) {
      const line = formatLabeledBlock(block);
      if (line) lines.push(line);
    }
  }
  return lines.join('\n');
}

/** Plain original wording for the clip studio's prompt field. */
export function breakpointSegmentUserPrompt(
  scene: ScriptScene,
  breakpointBlockIndex: number,
): string {
  const blocks = shootableSegmentBlocks(scene, breakpointBlockIndex);
  const hasScene = blocks.some((block) => block.type === 'scene');
  const parts: string[] = hasScene ? [scene.heading] : [sceneEnvironmentPrefix(scene)];
  for (const block of blocks) {
    const line = formatUserBlock(block);
    if (line) parts.push(line);
  }
  return parts.join('\n');
}

export function promptForBreakpointKey(document: ScriptDocument, key: string): string | null {
  const located = locateBreakpoint(document, key);
  if (!located) return null;
  return breakpointSegmentUserPrompt(located.scene, located.blockIndex);
}

/** Segment-owned shootable blocks, plus inherited environment when missing. */
export function displaySegmentBlocks(
  scene: ScriptScene,
  breakpointBlockIndex: number,
): {
  environment: ScriptBlock[];
  blocks: ScriptBlock[];
} {
  const blocks = shootableSegmentBlocks(scene, breakpointBlockIndex);
  const hasScene = blocks.some((block) => block.type === 'scene');
  return {
    environment: hasScene ? [] : sceneEnvironmentBlocks(scene),
    blocks,
  };
}

export function displaySegmentBlocksForKey(
  document: ScriptDocument,
  key: string,
): { environment: ScriptBlock[]; blocks: ScriptBlock[]; heading: string } | null {
  const located = locateBreakpoint(document, key);
  if (!located) return null;
  return {
    heading: located.scene.heading,
    ...displaySegmentBlocks(located.scene, located.blockIndex),
  };
}

/** Character/scene skill ids already linked on this episode's script. */
export function episodeLinkedAssetIds(document: ScriptDocument): {
  characterIds: string[];
  sceneIds: string[];
} {
  return {
    characterIds: document.characters
      .map((character) => character.character_ref_id)
      .filter((id): id is string => Boolean(id)),
    sceneIds: document.scenes
      .map((scene) => scene.ref_id)
      .filter((id): id is string => Boolean(id)),
  };
}

export function composeClipPrompt(userPrompt: string, labeledSegment: string): string {
  const user = userPrompt.trim();
  const labeled = labeledSegment.trim();
  const combined = user && labeled && user !== labeled ? `${user}\n\n${labeled}` : user || labeled;
  return combined.slice(0, STUDIO_PROMPT_MAX_LENGTH);
}

/**
 * Replaces only this segment's shootable block texts. `nextBlocks` must be
 * the same length and types (polish is in-place). Inherited environment
 * blocks are ignored if the caller prepended them.
 */
export function applySegmentBlockTexts(
  document: ScriptDocument,
  key: string,
  nextBlocks: ScriptBlock[],
): ScriptDocument | null {
  const located = locateBreakpoint(document, key);
  if (!located) return null;
  const current = shootableSegmentBlocks(located.scene, located.blockIndex);
  let source = nextBlocks.filter((block) => block.type !== 'breakpoint');
  while (
    source.length > current.length &&
    source[0]?.type === 'scene' &&
    current[0]?.type !== 'scene'
  ) {
    source = source.slice(1);
  }
  if (source.length !== current.length) return null;
  if (source.some((block, index) => block.type !== current[index]?.type)) return null;

  const segment = breakpointSegmentBlocks(located.scene, located.blockIndex);
  const segmentStart = located.blockIndex - segment.length;
  const nextScenes = document.scenes.map((scene) => {
    if (scene !== located.scene) return scene;
    let shootableIndex = 0;
    return {
      ...scene,
      blocks: scene.blocks.map((block, index) => {
        if (index < segmentStart || index >= located.blockIndex) return block;
        if (block.type === 'breakpoint') return block;
        const replacement = source[shootableIndex];
        shootableIndex += 1;
        return replacement
          ? { ...block, text: replacement.text, character: block.character }
          : block;
      }),
    };
  });
  return { ...document, scenes: nextScenes };
}
