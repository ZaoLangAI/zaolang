import type { ScriptCharacter, ScriptDocument, ScriptEmotion, ScriptScene } from './api';
import {
  locateBreakpoint,
  orderedBreakpointKeys,
  type BreakpointVideoBinding,
} from './script-breakpoint';
import { breakpointSegmentPrompt, resolveBreakpointRefs } from './script-prompts';

/** A video segment the batch runner can submit, in shoot order. */
export interface PendingVideo {
  key: string;
  heading: string;
  blockIndex: number;
  characterIds: string[];
  sceneId: string | null;
  prompt: string;
}

/** One dialogue line the batch runner can dub, in script order — the unit
 * for `BatchKind: 'audio'` is a single `type: 'dialogue'` block rather than
 * a whole breakpoint segment (a scene may have many spoken lines between
 * two breakpoints, each needing its own voice clip). */
export interface PendingAudio {
  key: string;
  heading: string;
  blockIndex: number;
  character: string | null;
  /** What gets spoken — a leading 「（冷笑）」-style direction is removed. */
  text: string;
  /** The block's own `emotion`, else one read from that direction. Optional
   * only because batches persisted before this field lack it. */
  emotion?: ScriptEmotion | null;
}

// Checked in order: a sneer or wry smile is not "happy", so it is claimed
// (with no emotion) before the plain 笑 rule can.
const DIRECTION_EMOTIONS: ReadonlyArray<readonly [RegExp, ScriptEmotion | null]> = [
  [/冷笑|苦笑|讥|嘲|讽/, null],
  [/哭|哽咽|难过|伤心|悲|委屈/, 'sad'],
  [/怒|吼|生气|咬牙|厉声/, 'angry'],
  [/害怕|恐|颤抖|发抖|慌/, 'fear'],
  [/惊讶|诧异|震惊|愣住/, 'surprise'],
  [/笑|开心|高兴|兴奋|欢快/, 'happy'],
  [/平静|淡淡|冷静/, 'calm'],
];

/**
 * Splits a leading stage direction off a dialogue line — 「（冷笑）你也配？」
 * → line 「你也配？」, direction 「冷笑」 — so TTS never reads the direction
 * aloud, and maps the direction onto the closed emotion set when it can.
 * A line that is nothing but a parenthetical is left whole.
 */
export function parseDialogueDirection(text: string): {
  line: string;
  direction: string | null;
  emotion: ScriptEmotion | null;
} {
  const match = /^\s*[（(]([^（）()]{1,12})[）)]\s*/.exec(text);
  const line = match ? text.slice(match[0].length).trim() : '';
  if (!match || !line) return { line: text.trim(), direction: null, emotion: null };
  const direction = (match[1] ?? '').trim();
  const emotion = DIRECTION_EMOTIONS.find(([pattern]) => pattern.test(direction))?.[1] ?? null;
  return { line, direction, emotion };
}

/** `{heading}#L{blockIndex}` — stable because `blockIndex` never shifts for
 * existing blocks once the script stops streaming (edits append/replace
 * blocks in place, they do not resplice earlier indices). Deliberately a
 * different shape than `breakpointKey`'s `{heading}#{ordinal}` so a video
 * draft and an audio draft linked to the "same" scene can never collide on
 * `link_breakpoint_key`. */
export function dialogueLineKey(heading: string, blockIndex: number): string {
  return `${heading}#L${blockIndex}`;
}

export function pendingCharacters(
  document: ScriptDocument,
  inFlightNames: ReadonlySet<string> = new Set(),
): ScriptCharacter[] {
  return document.characters.filter(
    (character) => !character.character_ref_id && !inFlightNames.has(character.name),
  );
}

/** A character-library row the batch dialog can match by trimmed name. */
export interface LibraryCharacterMatch {
  id: string;
  name: string;
  created_at?: string;
}

export function libraryCharacterByName<T extends LibraryCharacterMatch>(
  characters: readonly T[],
): Map<string, T> {
  const byName = new Map<string, T>();
  for (const character of characters) {
    const key = character.name.trim();
    if (!key) continue;
    const current = byName.get(key);
    if (!current || (character.created_at ?? '') > (current.created_at ?? '')) {
      byName.set(key, character);
    }
  }
  return byName;
}

/** Unlinked script characters whose trimmed name already exists in the library. */
export function existingLibraryMatches(
  document: ScriptDocument,
  library: readonly LibraryCharacterMatch[],
  inFlightNames: ReadonlySet<string> = new Set(),
): Array<{ name: string; refId: string }> {
  const byName = libraryCharacterByName(library);
  const matches: Array<{ name: string; refId: string }> = [];
  for (const character of pendingCharacters(document, inFlightNames)) {
    const existing = byName.get(character.name.trim());
    if (existing) matches.push({ name: character.name, refId: existing.id });
  }
  return matches;
}

export function pendingScenes(
  document: ScriptDocument,
  inFlightHeadings: ReadonlySet<string> = new Set(),
): ScriptScene[] {
  return document.scenes.filter((scene) => !scene.ref_id && !inFlightHeadings.has(scene.heading));
}

export function linkedCharacterCount(document: ScriptDocument): number {
  return document.characters.filter((character) => character.character_ref_id).length;
}

export function linkedSceneCount(document: ScriptDocument): number {
  return document.scenes.filter((scene) => scene.ref_id).length;
}

export function hasLinkedReference(document: ScriptDocument): boolean {
  return (
    document.characters.some((character) => Boolean(character.character_ref_id)) ||
    document.scenes.some((scene) => Boolean(scene.ref_id))
  );
}

function segmentHasRefs(
  document: ScriptDocument,
  scene: ScriptScene,
  blockIndex: number,
): boolean {
  const refs = resolveBreakpointRefs(document, scene, blockIndex);
  return refs.characterIds.length > 0 || Boolean(refs.sceneId);
}

export function pendingVideos(
  document: ScriptDocument,
  bindings: Record<string, BreakpointVideoBinding>,
  inFlightKeys: ReadonlySet<string> = new Set(),
): PendingVideo[] {
  const pending: PendingVideo[] = [];
  for (const key of orderedBreakpointKeys(document)) {
    if (key in bindings || inFlightKeys.has(key)) continue;
    const located = locateBreakpoint(document, key);
    if (!located || !segmentHasRefs(document, located.scene, located.blockIndex)) continue;
    const refs = resolveBreakpointRefs(document, located.scene, located.blockIndex);
    pending.push({
      key,
      heading: located.scene.heading,
      blockIndex: located.blockIndex,
      characterIds: refs.characterIds,
      sceneId: refs.sceneId,
      prompt: breakpointSegmentPrompt(located.scene, located.blockIndex),
    });
  }
  return pending;
}

export function boundVideoCount(
  document: ScriptDocument,
  bindings: Record<string, BreakpointVideoBinding>,
): number {
  return orderedBreakpointKeys(document).filter((key) => key in bindings).length;
}

/** Unbound segments that still have no character or scene ref to generate from. */
export function unreferencedVideoKeys(
  document: ScriptDocument,
  bindings: Record<string, BreakpointVideoBinding>,
): string[] {
  const keys: string[] = [];
  for (const key of orderedBreakpointKeys(document)) {
    if (key in bindings) continue;
    const located = locateBreakpoint(document, key);
    if (!located || segmentHasRefs(document, located.scene, located.blockIndex)) continue;
    keys.push(key);
  }
  return keys;
}

export function batchItemKey(kind: 'character' | 'scene' | 'video', id: string): string {
  return `${kind}:${id}`;
}

/** Every spoken line still needing a voice clip, in script order. Unlike
 * `pendingVideos`, this does not require a character/scene ref — dubbing
 * only needs the line's own text, so a fresh script with no library links
 * yet can still be batch-dubbed. */
export function pendingDialogueLines(
  document: ScriptDocument,
  dubbedKeys: ReadonlySet<string> = new Set(),
  inFlightKeys: ReadonlySet<string> = new Set(),
): PendingAudio[] {
  const pending: PendingAudio[] = [];
  for (const scene of document.scenes) {
    scene.blocks.forEach((block, blockIndex) => {
      if (block.type !== 'dialogue' || !block.text.trim()) return;
      const key = dialogueLineKey(scene.heading, blockIndex);
      if (dubbedKeys.has(key) || inFlightKeys.has(key)) return;
      const spoken = parseDialogueDirection(block.text);
      const emotion = block.emotion ?? spoken.emotion;
      pending.push({
        key,
        heading: scene.heading,
        blockIndex,
        character: block.character,
        text: spoken.line,
        ...(emotion ? { emotion } : {}),
      });
    });
  }
  return pending;
}
