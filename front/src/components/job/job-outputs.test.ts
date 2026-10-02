import { describe, expect, it } from 'vitest';

import { jobOutputs, partialDelivery } from './job-outputs';

describe('jobOutputs', () => {
  it('reads the singular fields, which is what an ordinary job sets', () => {
    // The plural pair stays null for a single-output job; a reader that only
    // looked at `output_urls` would render nothing for almost every job.
    expect(jobOutputs({ output_url: 'a.png', output_asset_id: 'ast_1' })).toEqual({
      urls: ['a.png'],
      assetIds: ['ast_1'],
    });
  });

  it('prefers the plural fields when a multi-output job populated them', () => {
    expect(
      jobOutputs({
        output_url: 'front.png',
        output_urls: ['front.png', 'side.png'],
        output_asset_id: 'ast_1',
        output_asset_ids: ['ast_1', 'ast_2'],
      }),
    ).toEqual({ urls: ['front.png', 'side.png'], assetIds: ['ast_1', 'ast_2'] });
  });

  it('ignores an empty plural array rather than treating it as an answer', () => {
    expect(jobOutputs({ output_url: 'a.png', output_urls: [] }).urls).toEqual(['a.png']);
  });

  it('is empty for a job with no output, and for no job at all', () => {
    expect(jobOutputs({})).toEqual({ urls: [], assetIds: [] });
    expect(jobOutputs(null)).toEqual({ urls: [], assetIds: [] });
  });
});

describe('partialDelivery', () => {
  const job = {
    status: 'succeeded',
    requested_outputs: 3,
    output_asset_id: 'ast_1',
    output_asset_ids: ['ast_1', 'ast_2'],
  };

  it('reports how many of the priced images a succeeded job delivered', () => {
    expect(partialDelivery(job)).toEqual({ delivered: 2, requested: 3 });
  });

  it('is null once every priced image arrived', () => {
    expect(partialDelivery({ ...job, output_asset_ids: ['ast_1', 'ast_2', 'ast_3'] })).toBeNull();
  });

  it('is null for a single-image job and for a job that has not succeeded', () => {
    expect(partialDelivery({ ...job, requested_outputs: 1 })).toBeNull();
    expect(partialDelivery({ ...job, status: 'running' })).toBeNull();
  });
});
