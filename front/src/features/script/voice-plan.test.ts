import { describe, expect, it } from 'vitest';

import type { CharacterVoice } from '@/lib/api/types';

import type { ScriptDocument } from './api';
import type { PendingAudio } from './batch-plan';
import { defaultSpeakerVoice, dialogueSpeakers, voiceAssignments } from './voice-plan';

const voice = (id: string, extra: Partial<CharacterVoice> = {}) =>
  ({ id, name: id, source: 'preset', is_default: false, look_ids: [], ...extra }) as CharacterVoice;

const document = {
  title: '',
  logline: '',
  characters: [
    { name: '林夏', traits: '', character_ref_id: 'sk_lin', look_id: 'skv_old' },
    { name: '周岩', traits: '', character_ref_id: 'sk_zhou', look_id: null },
    { name: '路人', traits: '', character_ref_id: null },
  ],
  scenes: [],
} as unknown as ScriptDocument;

const line = (character: string | null, n: number) =>
  ({ key: `k${n}`, heading: 'h', blockIndex: n, character, text: '…' }) as PendingAudio;

describe('dialogueSpeakers', () => {
  it('groups lines by speaker with their script links', () => {
    const speakers = dialogueSpeakers(document, [
      line('林夏', 1),
      line('周岩', 2),
      line('林夏', 3),
      line('路人', 4),
      line(null, 5),
    ]);
    expect(speakers).toEqual([
      { speaker: '林夏', cardId: 'sk_lin', lookId: 'skv_old', lines: 2 },
      { speaker: '周岩', cardId: 'sk_zhou', lookId: null, lines: 1 },
      { speaker: '路人', cardId: null, lookId: null, lines: 1 },
      { speaker: '', cardId: null, lookId: null, lines: 1 },
    ]);
  });
});

describe('defaultSpeakerVoice / voiceAssignments', () => {
  const linVoices = [voice('daily', { is_default: true }), voice('old', { look_ids: ['skv_old'] })];
  const zhouVoices = [voice('zhou_a'), voice('zhou_b', { is_default: true })];

  it('prefers the voice bound to the script’s look, then the default', () => {
    expect(defaultSpeakerVoice(linVoices, 'skv_old')).toMatchObject({
      voice: { id: 'old' },
      source: 'look',
    });
    expect(defaultSpeakerVoice(linVoices, null)).toMatchObject({
      voice: { id: 'daily' },
      source: 'default',
    });
    expect(defaultSpeakerVoice([], null)).toBeNull();
  });

  it('assigns voices per speaker; an explicit pick (or global) wins', () => {
    const speakers = dialogueSpeakers(document, [
      line('林夏', 1),
      line('周岩', 2),
      line('路人', 3),
    ]);
    const voicesByCard = { sk_lin: linVoices, sk_zhou: zhouVoices };
    expect(voiceAssignments(speakers, voicesByCard, {})).toEqual({ 林夏: 'old', 周岩: 'zhou_b' });
    expect(voiceAssignments(speakers, voicesByCard, { 林夏: 'daily', 周岩: '' })).toEqual({
      林夏: 'daily',
    });
  });
});
