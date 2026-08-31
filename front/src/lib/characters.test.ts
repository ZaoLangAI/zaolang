import { describe, expect, it } from 'vitest';

import type { GenerationJob } from '@/lib/api/types';

import { findCompletionJobFor, isCharacterCompletionJob } from './characters';

function job(overrides: Partial<GenerationJob>): GenerationJob {
  return {
    id: 'job_front',
    status: 'succeeded',
    operation: 'text_to_image',
    quality_tier: 'standard',
    progress: 100,
    quoted_credits: 12,
    reserved_credits: 12,
    estimated_seconds: 10,
    cancel_requested: false,
    created_at: '2026-08-30T00:00:00Z',
    asset_kind: 'character',
    ...overrides,
  };
}

describe('isCharacterCompletionJob', () => {
  it('is a character job whose views omit front', () => {
    expect(
      isCharacterCompletionJob(job({ character_views: ['side', 'back'] })),
    ).toBe(true);
    expect(isCharacterCompletionJob(job({ character_views: ['front'] }))).toBe(false);
    expect(isCharacterCompletionJob(job({ asset_kind: 'scene' }))).toBe(false);
  });
});

describe('findCompletionJobFor', () => {
  const front = job({
    id: 'job_front',
    linked_character_id: 'skl_char',
    character_views: ['front'],
    created_at: '2026-08-30T00:00:00Z',
  });

  it('returns an in-flight completion in the same window', () => {
    const completing = job({
      id: 'job_side',
      status: 'running',
      linked_character_id: 'skl_char',
      character_views: ['side', 'back'],
      created_at: '2026-08-30T00:01:00Z',
    });
    expect(findCompletionJobFor([front, completing], front)?.id).toBe('job_side');
  });

  it('ignores a failed or cancelled completion so the button can be offered again', () => {
    const failed = job({
      id: 'job_failed',
      status: 'failed',
      linked_character_id: 'skl_char',
      character_views: ['side', 'back'],
      created_at: '2026-08-30T00:01:00Z',
    });
    const cancelled = job({
      id: 'job_cancelled',
      status: 'cancelled',
      linked_character_id: 'skl_char',
      character_views: ['side', 'back'],
      created_at: '2026-08-30T00:02:00Z',
    });
    expect(findCompletionJobFor([front, failed, cancelled], front)).toBeNull();
  });

  it('prefers a later succeeded completion over an earlier failed one', () => {
    const failed = job({
      id: 'job_failed',
      status: 'failed',
      linked_character_id: 'skl_char',
      character_views: ['side', 'back'],
      created_at: '2026-08-30T00:01:00Z',
    });
    const succeeded = job({
      id: 'job_ok',
      status: 'succeeded',
      linked_character_id: 'skl_char',
      character_views: ['side', 'back'],
      created_at: '2026-08-30T00:02:00Z',
    });
    expect(findCompletionJobFor([front, failed, succeeded], front)?.id).toBe('job_ok');
  });
});
