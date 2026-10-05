import { describe, expect, it } from 'vitest';

import type { AssetGraph, CharacterVoice, GenerationModelOption } from '@/lib/api/types';

import { buildVoiceGraph, voiceRows } from './graph-model';
import { voiceBody, voiceDraft } from './inspector/voice-form';

const voice = (id: string, extra: Partial<CharacterVoice> = {}) =>
  ({
    id,
    name: id,
    source: 'preset',
    model: 'tts-pro',
    voice: '柔美女友',
    params: { speed: null, emotion: null },
    attributes: { custom: [] },
    look_ids: [],
    is_default: false,
    sort_order: 0,
    ...extra,
  }) as CharacterVoice;

const graph = (voices: CharacterVoice[], extra: Partial<AssetGraph> = {}) =>
  ({
    card_id: 'sk_1',
    card_kind: 'character',
    name: '林夏',
    variants: [{ id: 'young', name: '少年', is_default: true, sort_order: 0, entries: [] }],
    voices,
    edges: [],
    pending: [],
    caps: { max_entries_per_variant: 24, max_edges: 2000 },
    ...extra,
  }) as unknown as AssetGraph;

describe('buildVoiceGraph', () => {
  it('draws voices with their looks, previews and voice edges only', () => {
    const data = graph([voice('daily', { look_ids: ['young'] }), voice('old')], {
      edges: [
        {
          id: 'e1',
          level: 'voice',
          source_id: 'daily',
          target_id: 'old',
          relations: ['age'],
          origin: 'auto',
        },
        {
          id: 'e2',
          level: 'variant',
          source_id: 'a',
          target_id: 'b',
          relations: ['age'],
          origin: 'manual',
        },
      ] as AssetGraph['edges'],
      pending: [
        { job_id: 'j', status: 'running', target_voice_id: 'old' },
      ] as AssetGraph['pending'],
    });
    const built = buildVoiceGraph(data, { type: 'voice', id: 'old' });
    expect(built.nodes.map((n) => n.id)).toEqual(['c:daily', 'c:old']);
    const daily = built.nodes[0]!;
    const old = built.nodes[1]!;
    expect(daily.type === 'voice' && daily.data.lookNames).toEqual(['少年']);
    expect(old.type === 'voice' && old.data.previewPending).toBe(true);
    expect(old.selected).toBe(true);
    expect(built.edges.map((e) => [e.source, e.target])).toEqual([['c:daily', 'c:old']]);
    expect(built.rankPairs).toEqual([['c:daily', 'c:old']]);
  });

  it('lists a voice’s attribute rows', () => {
    const rows = voiceRows(
      voice('v', {
        attributes: {
          age_stage: 'elderly',
          emotion: '哭腔',
          use: 'narration',
          custom: [{ key: '口音', value: '京腔' }],
        },
      }),
    );
    expect(rows.map((row) => row.key)).toEqual([
      'age_stage',
      'voice_emotion',
      'voice_use',
      'custom',
    ]);
  });
});

describe('voiceBody', () => {
  const tts1 = {
    model: 'tts-1',
    label: 'TTS-1',
    voices: ['nova'],
    voice_params: ['speed'],
    voice_emotions: [],
  } as unknown as GenerationModelOption;

  it('keeps only the knobs the picked model takes', () => {
    const draft = {
      ...voiceDraft(null, '快'),
      model: 'tts-1',
      voice: 'nova',
      speed: 1.5,
      emotion: 'happy',
    };
    const body = voiceBody(draft, tts1);
    expect(body.params).toEqual({ speed: 1.5 });
    expect(body.voice).toBe('nova');
    expect(body.sample_asset_id).toBeNull();
  });

  it('sends a clone’s sample and no preset voice', () => {
    const draft = {
      ...voiceDraft(null, '克隆'),
      source: 'clone' as const,
      voice: 'nova',
      sampleAssetId: 'ast_1',
    };
    const body = voiceBody(draft);
    expect(body.voice).toBeNull();
    expect(body.sample_asset_id).toBe('ast_1');
    expect(body.params).toEqual({});
  });
});
