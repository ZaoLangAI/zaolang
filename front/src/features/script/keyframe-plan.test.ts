import { describe, expect, it } from 'vitest';

import type { Draft } from '@/lib/api/types';

import type { ScriptDocument } from './api';
import { keyframeTask, pendingKeyframes, pendingVideos, unreferencedVideoKeys } from './batch-plan';
import {
  confirmedFirstFrames,
  indexBreakpointKeyframes,
  indexBreakpointVideos,
  keyframeKey,
} from './script-breakpoint';

const document: ScriptDocument = {
  title: '雨夜',
  logline: '',
  characters: [{ name: '林夏', traits: '', character_ref_id: 'chr_1' }],
  scenes: [
    {
      heading: '日·客厅',
      ref_id: null,
      blocks: [
        { type: 'dialogue', character: '林夏', text: '你还在等我？' },
        { type: 'breakpoint', character: null, text: '切' },
      ],
    },
    {
      heading: '夜·街道',
      ref_id: null,
      blocks: [
        { type: 'action', character: null, text: '空无一人的街道' },
        { type: 'breakpoint', character: null, text: '切' },
      ],
    },
  ],
};

const draft = (id: string, params: Record<string, unknown>, extra: Partial<Draft> = {}): Draft =>
  ({ id, created_at: '2026-09-14T00:00:00Z', params, ...extra }) as Draft;

describe('keyframeKey', () => {
  it('maps a segment key onto its keyframe slot', () => {
    expect(keyframeKey('日·客厅#0')).toBe('日·客厅#K0');
    expect(keyframeKey('第#3场#2')).toBe('第#3场#K2');
  });
});

describe('indexBreakpointKeyframes', () => {
  it('is confirmed only while the confirmed job is still the applied version', () => {
    const keyframes = indexBreakpointKeyframes([
      draft(
        'drf_a',
        {
          operation: 'text_to_image',
          link_breakpoint_key: '日·客厅#K0',
          keyframe_confirmed_job_id: 'job_1',
        },
        { applied_job_id: 'job_1', output_asset_id: 'ast_a', output_url: 'https://x/a.png' },
      ),
      // Regenerated after confirming: the applied version moved on.
      draft(
        'drf_b',
        {
          operation: 'text_to_image',
          link_breakpoint_key: '夜·街道#K0',
          keyframe_confirmed_job_id: 'job_2',
        },
        { applied_job_id: 'job_3', output_asset_id: 'ast_b' },
      ),
      draft('drf_v', { operation: 'text_to_video', link_breakpoint_key: '日·客厅#0' }),
    ]);
    expect(Object.keys(keyframes).sort()).toEqual(['夜·街道#0', '日·客厅#0']);
    expect(keyframes['日·客厅#0']).toMatchObject({ draftId: 'drf_a', confirmed: true });
    expect(keyframes['夜·街道#0']?.confirmed).toBe(false);
    expect(confirmedFirstFrames(keyframes)).toEqual({ '日·客厅#0': 'ast_a' });
  });
});

describe('indexBreakpointVideos', () => {
  it('binds a video generated from a keyframe but never the keyframe itself', () => {
    const bindings = indexBreakpointVideos(
      [
        draft('drf_i2v', { operation: 'image_to_video', link_breakpoint_key: '日·客厅#0' }),
        draft('drf_kf', { operation: 'text_to_image', link_breakpoint_key: '夜·街道#K0' }),
      ],
      document.scenes,
    );
    expect(Object.keys(bindings)).toEqual(['日·客厅#0']);
  });
});

describe('pendingKeyframes', () => {
  it('lists segments with neither a video nor a keyframe yet, with the segment prompt', () => {
    const pending = pendingKeyframes(
      document,
      {},
      { '日·客厅#0': { draftId: 'drf_a' } },
    );
    expect(pending.map((task) => task.key)).toEqual(['夜·街道#0']);
    expect(pending[0]?.prompt).toContain('空无一人的街道');
    expect(pending[0]?.prompt).toContain('分镜关键帧');
  });

  it('builds a regenerate task into the existing draft', () => {
    expect(keyframeTask(document, '日·客厅#0', 'drf_a')).toMatchObject({
      key: '日·客厅#0',
      characterIds: ['chr_1'],
      draftId: 'drf_a',
    });
    expect(keyframeTask(document, '不存在#0')).toBeNull();
  });
});

describe('pendingVideos with confirmed keyframes', () => {
  it('queues an unreferenced segment once it has a confirmed first frame', () => {
    expect(pendingVideos(document, {}).map((video) => video.key)).toEqual(['日·客厅#0']);
    const withFrame = pendingVideos(document, {}, new Set(), { '夜·街道#0': 'ast_kf' });
    expect(withFrame.map((video) => [video.key, video.firstFrameAssetId])).toEqual([
      ['日·客厅#0', null],
      ['夜·街道#0', 'ast_kf'],
    ]);
    expect(unreferencedVideoKeys(document, {}, { '夜·街道#0': 'ast_kf' })).toEqual([]);
  });
});
