import { describe, expect, it } from 'vitest';

import type { ScriptDocument } from '@/features/script/api';
import type { BreakpointVideoBinding } from '@/features/script/script-breakpoint';
import type { Draft, GenerationJob } from '@/lib/api/types';

import {
  creditsSpent,
  currentProductionStage,
  episodeProductionStages,
  productionShots,
  takeCount,
  unmatchedVideoDraftCount,
  type ProductionInput,
} from './production-stages';

const script: ScriptDocument = {
  title: '雨夜',
  logline: '',
  characters: [
    { name: '林夏', traits: '', character_ref_id: 'chr_1' },
    { name: '周屿', traits: '', character_ref_id: null },
  ],
  scenes: [
    {
      heading: '日·客厅',
      ref_id: 'scn_1',
      blocks: [
        { type: 'dialogue', character: '林夏', text: '你还在等我？' },
        { type: 'breakpoint', character: null, text: '切' },
        { type: 'dialogue', character: '周屿', text: '一直在。' },
      ],
    },
    {
      heading: '夜·街道',
      ref_id: null,
      blocks: [
        { type: 'action', character: null, text: '两人并肩' },
        { type: 'breakpoint', character: null, text: '切' },
      ],
    },
  ],
};

const binding = (draftId: string, outputAssetId: string | null): BreakpointVideoBinding => ({
  draftId,
  latestJobId: null,
  outputAssetId,
});

const draft = (id: string, overrides: Partial<Draft> = {}): Draft =>
  ({ id, created_at: '2026-09-14T00:00:00Z', ...overrides }) as Draft;

const job = (overrides: Partial<GenerationJob>): GenerationJob =>
  ({ id: 'job', status: 'succeeded', actual_credits: null, ...overrides }) as GenerationJob;

function input(overrides: Partial<ProductionInput> = {}): ProductionInput {
  return {
    hasScript: true,
    script,
    bindings: {},
    dubbedKeys: new Set(),
    cutCount: 0,
    exportStatuses: [],
    published: false,
    ...overrides,
  };
}

describe('episodeProductionStages', () => {
  it('counts linked characters and scenes, ready shots and dubbed lines', () => {
    const stages = episodeProductionStages(
      input({
        bindings: { '日·客厅#0': binding('drf_a', 'ast_a'), '日·客厅#1': binding('drf_b', null) },
        dubbedKeys: new Set(['日·客厅#L0']),
      }),
    );
    const byKey = Object.fromEntries(stages.map((stage) => [stage.key, stage]));
    expect(byKey.script?.state).toBe('done');
    expect(byKey.characters).toMatchObject({ state: 'active', done: 1, total: 2 });
    expect(byKey.scenes).toMatchObject({ state: 'active', done: 1, total: 2 });
    // 日·客厅 has a trailing closer (#1) after its breakpoint; 夜·街道 has #0.
    expect(byKey.shots).toMatchObject({ state: 'active', done: 1, total: 3 });
    expect(byKey.voice).toMatchObject({ state: 'active', done: 1, total: 2 });
    expect(byKey.edit?.state).toBe('todo');
    expect(currentProductionStage(stages)).toBe('characters');
  });

  it('marks an in-flight export active and a succeeded one done', () => {
    const inFlight = episodeProductionStages(input({ exportStatuses: ['rendering'] }));
    expect(inFlight.find((stage) => stage.key === 'export')?.state).toBe('active');
    const done = episodeProductionStages(input({ exportStatuses: ['failed', 'succeeded'] }));
    expect(done.find((stage) => stage.key === 'export')?.state).toBe('done');
  });

  it('treats a stage with nothing to do as done, but a script with no breakpoints as unshot', () => {
    const bare: ScriptDocument = { title: '', logline: '', characters: [], scenes: [] };
    const stages = episodeProductionStages(input({ script: bare }));
    const byKey = Object.fromEntries(stages.map((stage) => [stage.key, stage]));
    expect(byKey.characters?.state).toBe('done');
    expect(byKey.voice?.state).toBe('done');
    expect(byKey.shots?.state).toBe('todo');
    expect(currentProductionStage(stages)).toBe('shots');
  });

  it('shows nothing done before the script exists', () => {
    const stages = episodeProductionStages(input({ hasScript: false }));
    expect(stages.every((stage) => stage.state === 'todo')).toBe(true);
    expect(currentProductionStage(stages)).toBe('script');
  });
});

describe('productionShots', () => {
  it('lists every segment in shoot order with a real duration only once generated', () => {
    const shots = productionShots(
      script,
      { '日·客厅#0': binding('drf_a', 'ast_a'), '夜·街道#0': binding('drf_b', null) },
      { drf_a: draft('drf_a', { duration_ms: 8_000 }), drf_b: draft('drf_b', { duration_ms: 5_000 }) },
    );
    expect(shots.map((shot) => [shot.label, shot.status, shot.durationSeconds])).toEqual([
      ['S01·1', 'ready', 8],
      ['S01·2', 'missing', null],
      ['S02·1', 'generating', null],
    ]);
  });

  it('calls a bound segment failed once every one of its jobs ended without a success', () => {
    const bindings = { '夜·街道#0': binding('drf_b', null) };
    const drafts = { drf_b: draft('drf_b') };
    const status = (jobs: GenerationJob[]) =>
      productionShots(script, bindings, drafts, { drf_b: jobs }).at(-1)?.status;
    expect(status([job({ status: 'failed' }), job({ status: 'cancelled' })])).toBe('failed');
    expect(status([job({ status: 'failed' }), job({ status: 'running' })])).toBe('generating');
    expect(status([])).toBe('generating');
  });
});

describe('unmatchedVideoDraftCount', () => {
  it('counts video drafts bound to a segment the script no longer has', () => {
    const drafts = [
      draft('a', { params: { operation: 'text_to_video', link_breakpoint_key: '日·客厅#0' } }),
      draft('b', { params: { operation: 'text_to_video', link_breakpoint_key: '旧场景#0' } }),
      draft('c', { params: { operation: 'audio_generation', link_breakpoint_key: '旧场景#L1' } }),
    ];
    expect(unmatchedVideoDraftCount(script, drafts)).toBe(1);
  });
});

describe('spend and takes', () => {
  it('counts only charged credits and succeeded takes', () => {
    const jobs = [
      job({ id: '1', actual_credits: 40 }),
      job({ id: '2', status: 'failed', actual_credits: 0 }),
      job({ id: '3', status: 'running', actual_credits: null }),
      job({ id: '4', actual_credits: 25 }),
    ];
    expect(creditsSpent(jobs)).toBe(65);
    expect(takeCount(jobs)).toBe(2);
  });
});
