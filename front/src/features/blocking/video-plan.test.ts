import { describe, expect, it } from 'vitest';

import type { ScriptDocument } from '@/features/script/api';

import type { BlockingDocument } from './types';
import { castLegend, planSegmentVideo, planSegmentVideos } from './video-plan';

const script: ScriptDocument = {
  title: 't',
  logline: '',
  characters: [
    { name: '林夏', traits: '', character_ref_id: 'chr_lin' },
    { name: '陈默', traits: '', character_ref_id: null },
  ],
  scenes: [
    {
      heading: '便利店',
      ref_id: 'scn_store',
      blocks: [
        { type: 'scene', character: null, text: '深夜的便利店' },
        { type: 'dialogue', character: '林夏', text: '你来了。' },
        { type: 'breakpoint', character: null, text: 'cut' },
        { type: 'action', character: null, text: '陈默推门进来' },
      ],
    },
  ],
};

const shot = {
  t0: 0,
  transition: 'cut' as const,
  size: 'medium' as const,
  lens_mm: 35,
  height: 'eye' as const,
  side: 'front' as const,
  subject: null,
  over: null,
  move: { preset: 'static' as const, intensity: 0.5, ease: 'in_out' as const },
};

const document: BlockingDocument = {
  version: 1,
  script_hash: 'x',
  target_duration_s: 14,
  aspect_ratio: '9:16',
  sets: [],
  cast: [
    { id: 'lin', name: '林夏', character_ref_id: 'chr_lin', color_index: 0, height_m: 1.65 },
    { id: 'chen', name: '陈默', character_ref_id: null, color_index: 1, height_m: 1.8 },
  ],
  segments: [
    {
      key: '便利店#0',
      heading: '便利店',
      set_id: 's1',
      source_hash: '0',
      duration_s: 6,
      start: [
        {
          cast_id: 'lin',
          at: { anchor: null, x: 0, z: 0 },
          face: { target: null, deg: 0 },
          action: 'stand',
        },
      ],
      beats: [],
      shots: [shot],
      camera_override: null,
    },
    {
      key: '便利店#1',
      heading: '便利店',
      set_id: 's1',
      source_hash: '0',
      duration_s: 8,
      start: [
        {
          cast_id: 'lin',
          at: { anchor: null, x: 0, z: 0 },
          face: { target: null, deg: 0 },
          action: 'stand',
        },
        {
          cast_id: 'chen',
          at: { anchor: null, x: 1, z: 0 },
          face: { target: null, deg: 0 },
          action: 'stand',
        },
      ],
      beats: [],
      shots: [shot],
      camera_override: null,
    },
  ],
};

describe('planSegmentVideo', () => {
  it("uses the blockout's own duration, cast and the scene link", () => {
    const plan = planSegmentVideo(document, script, '便利店#1');
    expect(plan).toMatchObject({
      key: '便利店#1',
      durationSeconds: 8,
      characterIds: ['chr_lin'],
      sceneId: 'scn_store',
      unlinkedCast: ['陈默'],
    });
  });

  it('leads the prompt with the colour legend the reference clip needs', () => {
    const plan = planSegmentVideo(document, script, '便利店#1')!;
    expect(plan.prompt.startsWith('参考视频中红色人偶是林夏，蓝色人偶是陈默。')).toBe(true);
    expect(plan.prompt).toContain('陈默推门进来');
    expect(castLegend(document, '便利店#0')).toBe('参考视频中红色人偶是林夏。');
  });

  it('skips keys the script or blockout no longer has', () => {
    expect(planSegmentVideos(document, script, ['便利店#0', '便利店#9'])).toHaveLength(1);
  });
});
