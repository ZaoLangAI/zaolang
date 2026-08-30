import { describe, expect, it } from 'vitest';

import type { Draft } from '@/lib/api/types';

import { generatedVideoDetailHref, isGeneratedVideoCard } from './generated-video-href';

const draft = (overrides: Partial<Draft> = {}): Draft =>
  ({
    id: overrides.id ?? 'drf_1',
    created_at: '2026-08-28T00:00:00Z',
    ...overrides,
  }) as Draft;

describe('generatedVideoDetailHref', () => {
  it('routes a work link to the work page without waiting for work details', () => {
    expect(
      generatedVideoDetailHref({ contentType: 'work', contentRefId: 'w_abc' }),
    ).toBe('/work/w_abc');
  });

  it('routes a published draft to the published work', () => {
    expect(
      generatedVideoDetailHref({
        contentType: 'draft',
        contentRefId: 'drf_1',
        draft: draft({ published_work_id: 'w_pub', latest_job_id: 'job_old' }),
      }),
    ).toBe('/work/w_pub');
  });

  it('routes an unpublished draft with a job to the job page', () => {
    expect(
      generatedVideoDetailHref({
        contentType: 'draft',
        contentRefId: 'drf_1',
        draft: draft({ latest_job_id: 'job_abc' }),
      }),
    ).toBe('/jobs/job_abc');
  });

  it('returns undefined when the draft has no job yet', () => {
    expect(
      generatedVideoDetailHref({
        contentType: 'draft',
        contentRefId: 'drf_1',
        draft: draft({ latest_job_id: null, published_work_id: null }),
      }),
    ).toBeUndefined();
  });

  it('returns undefined when the draft record has not loaded', () => {
    expect(
      generatedVideoDetailHref({ contentType: 'draft', contentRefId: 'drf_1' }),
    ).toBeUndefined();
  });

  it('returns undefined for an unknown content type', () => {
    expect(
      generatedVideoDetailHref({ contentType: 'editor_export', contentRefId: 'exp_1' }),
    ).toBeUndefined();
  });
});

describe('isGeneratedVideoCard', () => {
  it('keeps a published work without waiting for extra details', () => {
    expect(isGeneratedVideoCard({ contentType: 'work' })).toBe(true);
  });

  it('keeps a draft that produced an output', () => {
    expect(
      isGeneratedVideoCard({
        contentType: 'draft',
        draft: draft({ output_asset_id: 'ast_1', latest_job_id: 'job_1' }),
      }),
    ).toBe(true);
  });

  it('keeps a draft that already published even if the asset id is gone', () => {
    expect(
      isGeneratedVideoCard({
        contentType: 'draft',
        draft: draft({ published_work_id: 'w_pub' }),
      }),
    ).toBe(true);
  });

  it('hides a failed or still-running draft with no output', () => {
    expect(
      isGeneratedVideoCard({
        contentType: 'draft',
        draft: draft({ latest_job_id: 'job_failed', output_asset_id: null }),
      }),
    ).toBe(false);
  });

  it('hides a draft whose record has not loaded yet', () => {
    expect(isGeneratedVideoCard({ contentType: 'draft' })).toBe(false);
  });
});
