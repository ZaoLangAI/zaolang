import { describe, expect, it } from 'vitest';

import type { Draft } from '@/lib/api/types';

import type { ScriptDocument, ScriptScene } from './api';
import {
  type BreakpointVideoBinding,
  breakpointKey,
  breakpointOrdinalInScene,
  breakpointSegmentBlocks,
  buildBreakpointVideoHref,
  dubbedDialogueKeys,
  indexBreakpointVideos,
  locateBreakpoint,
  orderedBreakpointKeys,
  parseBreakpointQueryKey,
  parseScriptDraftId,
  parseScriptEpisodeId,
  previousBoundVideoAssetId,
  resolveBreakpointHref,
  trailingBreakpoint,
} from './script-breakpoint';

const scene = (heading: string, breakpointCount: number): ScriptScene => ({
  heading,
  ref_id: null,
  blocks: Array.from({ length: breakpointCount }, (_, index) => ({
    type: 'breakpoint' as const,
    character: null,
    text: `cut ${index}`,
  })),
});

const draft = (overrides: Partial<Draft> & { params?: Draft['params'] }): Draft =>
  ({
    id: overrides.id ?? 'drf_1',
    created_at: '2026-08-28T00:00:00Z',
    latest_job_id: overrides.latest_job_id ?? 'job_1',
    output_asset_id: overrides.output_asset_id ?? 'ast_1',
    params: overrides.params ?? {},
  }) as Draft;

const document = (scenes: ScriptScene[]): ScriptDocument => ({
  title: '',
  logline: '',
  characters: [],
  scenes,
});

describe('clip-route id parsers', () => {
  it('accepts a well-formed episode / draft id and rejects junk', () => {
    expect(parseScriptEpisodeId('dep_01ABCDEFGH')).toBe('dep_01ABCDEFGH');
    expect(parseScriptEpisodeId('dep_' + 'A'.repeat(50))).toBeUndefined();
    expect(parseScriptEpisodeId('usr_1')).toBeUndefined();
    expect(parseScriptDraftId('drf_abc')).toBe('drf_abc');
    expect(parseScriptDraftId('job_abc')).toBeUndefined();
  });

  it('requires a heading#ordinal key', () => {
    expect(parseBreakpointQueryKey('雨巷#0')).toBe('雨巷#0');
    expect(parseBreakpointQueryKey('雨巷')).toBeUndefined();
    expect(parseBreakpointQueryKey('')).toBeUndefined();
  });
});

describe('breakpointKey / ordinal', () => {
  it('joins heading and 0-based ordinal', () => {
    expect(breakpointKey('内景 值班室', 0)).toBe('内景 值班室#0');
  });

  it('counts only breakpoint blocks before the current one', () => {
    const mixed: ScriptScene = {
      heading: '场',
      ref_id: null,
      blocks: [
        { type: 'action', character: null, text: 'a' },
        { type: 'breakpoint', character: null, text: 'one' },
        { type: 'dialogue', character: '林', text: 'hi' },
        { type: 'breakpoint', character: null, text: 'two' },
      ],
    };
    expect(breakpointOrdinalInScene(mixed, 1)).toBe(0);
    expect(breakpointOrdinalInScene(mixed, 3)).toBe(1);
  });
});

describe('buildBreakpointVideoHref', () => {
  it('points at the clip studio with only episode id and key', () => {
    const href = buildBreakpointVideoHref({
      episodeId: 'dep_1',
      key: '内景 值班室#0',
      characterIds: ['sk_char'],
      sceneId: 'sk_scene',
    });
    expect(href).toBeDefined();
    expect(href!.startsWith('/create/script/dep_1/clip?')).toBe(true);
    const query = new URLSearchParams(href!.split('?')[1]);
    expect(query.get('key')).toBe('内景 值班室#0');
    expect(query.has('prompt')).toBe(false);
    expect(query.has('mode')).toBe(false);
  });

  it('stays clickable when the segment has no character or scene refs', () => {
    const href = buildBreakpointVideoHref({
      episodeId: 'dep_1',
      key: '场#0',
      characterIds: [],
      sceneId: null,
    });
    expect(href).toBe('/create/script/dep_1/clip?key=%E5%9C%BA%230');
  });

  it('never auto-attaches a previous clip as a first frame', () => {
    const href = buildBreakpointVideoHref({
      episodeId: 'dep_1',
      key: '场#1',
      characterIds: ['sk_char'],
      sceneId: null,
    });
    const query = new URLSearchParams(href!.split('?')[1]);
    expect(query.has('continuityAssetId')).toBe(false);
  });
});

describe('orderedBreakpointKeys', () => {
  it("flattens every scene's breakpoints, then its trailing closer, in document order", () => {
    const doc = document([scene('场A', 2), scene('场B', 1)]);
    expect(orderedBreakpointKeys(doc)).toEqual(['场A#0', '场A#1', '场B#0']);
  });

  it("includes a trailing unclosed segment as the scene's last key", () => {
    const open: ScriptScene = {
      heading: '监听室',
      ref_id: null,
      blocks: [
        { type: 'breakpoint', character: null, text: 'cut' },
        { type: 'action', character: null, text: '开门' },
      ],
    };
    expect(orderedBreakpointKeys(document([open]))).toEqual(['监听室#0', '监听室#1']);
  });

  it('omits a scene with neither a real breakpoint nor shootable tail copy', () => {
    const empty: ScriptScene = { heading: '空场', ref_id: null, blocks: [] };
    expect(orderedBreakpointKeys(document([empty]))).toEqual([]);
  });
});

describe('locateBreakpoint', () => {
  it('finds a real breakpoint and a trailing closer', () => {
    const open: ScriptScene = {
      heading: '监听室',
      ref_id: null,
      blocks: [
        { type: 'breakpoint', character: null, text: 'cut' },
        { type: 'action', character: null, text: '开门' },
      ],
    };
    const doc = document([open]);
    expect(locateBreakpoint(doc, '监听室#0')?.blockIndex).toBe(0);
    expect(locateBreakpoint(doc, '监听室#1')?.blockIndex).toBe(2);
    expect(locateBreakpoint(doc, '不存在#0')).toBeNull();
  });
});

describe('previousBoundVideoAssetId', () => {
  const bound = (assetId: string): BreakpointVideoBinding => ({
    draftId: 'drf_x',
    latestJobId: 'job_x',
    outputAssetId: assetId,
  });

  it('returns null for the very first breakpoint in the whole document', () => {
    const doc = document([scene('场A', 1)]);
    expect(previousBoundVideoAssetId(doc, '场A#0', {})).toBeNull();
  });

  it('finds the nearest earlier bound video across scene boundaries, skipping unbound ones', () => {
    const doc = document([scene('场A', 2), scene('场B', 1)]);
    const bindings: Record<string, BreakpointVideoBinding> = { '场A#0': bound('ast_first') };
    expect(previousBoundVideoAssetId(doc, '场A#1', bindings)).toBe('ast_first');
    expect(previousBoundVideoAssetId(doc, '场B#0', bindings)).toBe('ast_first');
  });

  it('prefers the closest earlier bound video over an older one further back', () => {
    const doc = document([scene('场A', 1), scene('场B', 1), scene('场C', 1)]);
    const bindings: Record<string, BreakpointVideoBinding> = {
      '场A#0': bound('ast_old'),
      '场B#0': bound('ast_recent'),
    };
    expect(previousBoundVideoAssetId(doc, '场C#0', bindings)).toBe('ast_recent');
  });

  it('returns null when no earlier segment has a bound video yet', () => {
    const doc = document([scene('场A', 2)]);
    expect(previousBoundVideoAssetId(doc, '场A#1', {})).toBeNull();
  });
});

describe('resolveBreakpointHref', () => {
  it('routes a bound, already-generated clip into the studio to resume its draft', () => {
    expect(
      resolveBreakpointHref({
        episodeId: 'dep_1',
        key: '场#0',
        characterIds: ['sk_char'],
        sceneId: null,
        prompt: 'x',
        binding: { draftId: 'drf_abc', latestJobId: 'job_abc', outputAssetId: 'ast_1' },
      }),
    ).toEqual({
      href: '/create/script/dep_1/clip?key=%E5%9C%BA%230&draftId=drf_abc',
      viewGenerated: true,
    });
  });

  it('still resumes the draft (viewGenerated=false) when it has no output yet', () => {
    expect(
      resolveBreakpointHref({
        episodeId: 'dep_1',
        key: '场#0',
        characterIds: ['sk_char'],
        sceneId: null,
        prompt: 'x',
        binding: { draftId: 'drf_abc', latestJobId: null, outputAssetId: null },
      }),
    ).toEqual({
      href: '/create/script/dep_1/clip?key=%E5%9C%BA%230&draftId=drf_abc',
      viewGenerated: false,
    });
  });

  it('falls through to generate when nothing is bound', () => {
    const resolved = resolveBreakpointHref({
      episodeId: 'dep_1',
      key: '场#0',
      characterIds: ['sk_char'],
      sceneId: null,
      prompt: 'x',
    });
    expect(resolved.viewGenerated).toBe(false);
    expect(resolved.href).toContain('/create/script/dep_1/clip?');
    expect(resolved.href).toContain('key=');
  });

  it('still offers the clip studio when the cut has no linked scene or cast', () => {
    const resolved = resolveBreakpointHref({
      episodeId: 'dep_1',
      key: '场#4',
      characterIds: [],
      sceneId: null,
    });
    expect(resolved.viewGenerated).toBe(false);
    expect(resolved.href).toBe('/create/script/dep_1/clip?key=%E5%9C%BA%234');
  });
});

describe('indexBreakpointVideos', () => {
  it('prefers the stored breakpoint key', () => {
    const indexed = indexBreakpointVideos(
      [
        draft({
          params: { link_breakpoint_key: '走廊#0', prompt: '走廊，别的' },
        }),
      ],
      [scene('值班室', 1), scene('走廊', 1)],
    );
    expect(indexed['走廊#0']?.latestJobId).toBe('job_1');
    expect(indexed['值班室#0']).toBeUndefined();
  });

  it('falls back to prompt-prefix for keyless drafts', () => {
    const indexed = indexBreakpointVideos(
      [draft({ params: { prompt: '值班室，海拔两千米' } })],
      [scene('值班室', 1), scene('走廊', 1)],
    );
    expect(indexed['值班室#0']?.latestJobId).toBe('job_1');
    expect(indexed['走廊#0']).toBeUndefined();
  });

  it('does not steal a breakpoint that already has a keyed draft', () => {
    const indexed = indexBreakpointVideos(
      [
        draft({
          id: 'drf_keyed',
          latest_job_id: 'job_keyed',
          params: { link_breakpoint_key: '值班室#0' },
        }),
        draft({
          id: 'drf_old',
          latest_job_id: 'job_old',
          params: { prompt: '值班室，旧稿' },
        }),
      ],
      [scene('值班室', 1)],
    );
    expect(indexed['值班室#0']?.latestJobId).toBe('job_keyed');
  });

  it('binds a keyless draft onto the trailing unclosed segment', () => {
    const open: ScriptScene = {
      heading: '雷达峰顶',
      ref_id: null,
      blocks: [
        { type: 'action', character: null, text: '天线转向太阳' },
        { type: 'dialogue', character: '周岩', text: '他们回话了。' },
      ],
    };
    const indexed = indexBreakpointVideos(
      [draft({ params: { prompt: '雷达峰顶，黎明' } })],
      [open],
    );
    expect(indexed['雷达峰顶#0']?.latestJobId).toBe('job_1');
  });

  it('never binds an audio_generation draft onto a breakpoint, even with a matching key', () => {
    // A dubbing draft's `link_breakpoint_key` is `{heading}#L{blockIndex}`
    // (see `dialogueLineKey`), which cannot collide with `{heading}#
    // {ordinal}` — but this also guards the (impossible today, cheap to
    // keep guarding) case of an operation writing an ordinal-shaped key.
    const indexed = indexBreakpointVideos(
      [
        draft({
          id: 'drf_audio',
          params: {
            operation: 'audio_generation',
            link_breakpoint_key: '值班室#0',
            prompt: '值班室，海拔两千米',
          },
        }),
      ],
      [scene('值班室', 1)],
    );
    expect(indexed['值班室#0']).toBeUndefined();
  });

  it('still binds a text_to_video draft whose params say so explicitly', () => {
    const indexed = indexBreakpointVideos(
      [draft({ params: { operation: 'text_to_video', link_breakpoint_key: '值班室#0' } })],
      [scene('值班室', 1)],
    );
    expect(indexed['值班室#0']?.latestJobId).toBe('job_1');
  });
});

describe('dubbedDialogueKeys', () => {
  it('collects link_breakpoint_key from audio_generation drafts only', () => {
    const keys = dubbedDialogueKeys([
      draft({
        params: { operation: 'audio_generation', link_breakpoint_key: '公寓客厅#L1' },
      }),
      draft({
        id: 'drf_video',
        params: { operation: 'text_to_video', link_breakpoint_key: '公寓客厅#0' },
      }),
      draft({ id: 'drf_no_key', params: { operation: 'audio_generation' } }),
    ]);
    expect(keys).toEqual(new Set(['公寓客厅#L1']));
  });

  it('returns an empty set for no drafts', () => {
    expect(dubbedDialogueKeys([])).toEqual(new Set());
  });
});

describe('trailingBreakpoint', () => {
  it('returns heading#0 when a scene has shootable copy and no closer', () => {
    const open: ScriptScene = {
      heading: '监听室',
      ref_id: null,
      blocks: [
        { type: 'scene', character: null, text: '夜，水银灯' },
        { type: 'action', character: null, text: '周岩翻开台账' },
      ],
    };
    expect(trailingBreakpoint(open)).toEqual({ key: '监听室#0', blockIndex: 2 });
    expect(breakpointSegmentBlocks(open, 2).map((block) => block.type)).toEqual([
      'scene',
      'action',
    ]);
  });

  it('uses the next ordinal after existing breakpoints', () => {
    const mixed: ScriptScene = {
      heading: '值班室',
      ref_id: null,
      blocks: [
        { type: 'action', character: null, text: 'a' },
        { type: 'breakpoint', character: null, text: 'cut' },
        { type: 'dialogue', character: '林', text: 'hi' },
      ],
    };
    expect(trailingBreakpoint(mixed)).toEqual({ key: '值班室#1', blockIndex: 3 });
    expect(breakpointSegmentBlocks(mixed, 3).map((block) => block.text)).toEqual(['hi']);
  });

  it('is omitted when the last block is already a breakpoint', () => {
    expect(trailingBreakpoint(scene('走廊', 1))).toBeNull();
  });

  it('is omitted when the unclosed tail has no shootable copy', () => {
    const empty: ScriptScene = { heading: '空', ref_id: null, blocks: [] };
    expect(trailingBreakpoint(empty)).toBeNull();
  });
});
