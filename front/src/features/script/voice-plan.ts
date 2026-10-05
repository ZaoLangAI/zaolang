import type { CharacterVoice } from '@/lib/api/types';

import type { ScriptDocument } from './api';
import type { PendingAudio } from './batch-plan';

/** One speaker of a dubbing batch and the library card / look the script
 * links it to (`ScriptCharacter.character_ref_id` / `look_id`). */
export interface SpeakerLink {
  /** The dialogue block's `character`; `''` for unattributed lines. */
  speaker: string;
  cardId: string | null;
  lookId: string | null;
  lines: number;
}

/** Every speaker of `audios`, in order of first line. */
export function dialogueSpeakers(document: ScriptDocument, audios: PendingAudio[]): SpeakerLink[] {
  const cast = new Map(document.characters.map((character) => [character.name, character]));
  const speakers = new Map<string, SpeakerLink>();
  for (const audio of audios) {
    const speaker = (audio.character ?? '').trim();
    const known = speakers.get(speaker);
    if (known) {
      known.lines += 1;
      continue;
    }
    const linked = speaker ? cast.get(speaker) : undefined;
    speakers.set(speaker, {
      speaker,
      cardId: linked?.character_ref_id ?? null,
      lookId: linked?.character_ref_id ? (linked.look_id ?? null) : null,
      lines: 1,
    });
  }
  return [...speakers.values()];
}

export type VoiceSourceKind = 'look' | 'default' | 'global';

/** Which of a card's voices a speaker uses by default: the voice bound to
 * the script's look, else the card's default voice; `null` → the batch's
 * global voice. Mirrors `characters.voices.voice_for_look`. */
export function defaultSpeakerVoice(
  voices: CharacterVoice[],
  lookId: string | null,
): { voice: CharacterVoice; source: Exclude<VoiceSourceKind, 'global'> } | null {
  if (lookId) {
    const bound = voices.find((voice) => (voice.look_ids ?? []).includes(lookId));
    if (bound) return { voice: bound, source: 'look' };
  }
  const fallback = voices.find((voice) => voice.is_default) ?? voices[0];
  return fallback ? { voice: fallback, source: 'default' } : null;
}

/** `speaker → voice_profile_id` for the batch: an explicit pick (`''` =
 * the global voice) wins over the default. Speakers without a voice are
 * left out, so they dub with the global voice. */
export function voiceAssignments(
  speakers: SpeakerLink[],
  voicesByCard: Record<string, CharacterVoice[]>,
  overrides: Record<string, string>,
): Record<string, string> {
  const assigned: Record<string, string> = {};
  for (const link of speakers) {
    const picked = overrides[link.speaker];
    if (picked !== undefined) {
      if (picked) assigned[link.speaker] = picked;
      continue;
    }
    const resolved = link.cardId
      ? defaultSpeakerVoice(voicesByCard[link.cardId] ?? [], link.lookId)
      : null;
    if (resolved) assigned[link.speaker] = resolved.voice.id;
  }
  return assigned;
}
