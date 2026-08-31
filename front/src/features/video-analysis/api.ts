import { api } from '@/lib/api/client';
import type { GenerationJob, Page, QualityTier, Quote } from '@/lib/api/types';

/** Priced the same way as every other operation's quote — flat per tier,
 * `duration_seconds` left at its default since `video_analysis` pricing
 * never depends on it (see `DEFAULT_TIER_PRICING`). */
export function quoteVideoAnalysis(qualityTier: QualityTier): Promise<Quote> {
  return api.post<Quote>('/v1/generation-jobs/quote', {
    operation: 'video_analysis',
    quality_tier: qualityTier,
  });
}

export interface VideoAnalysisSubmitInput {
  qualityTier: QualityTier;
  referenceAssetId: string;
  notes: string;
  maxCredits?: number;
  /**
   * One key per pending submission, supplied by the caller so it survives a
   * retry after a network failure — minting a fresh key here on every call
   * would let a retry double-reserve credits for the same analysis. See
   * `useVideoAnalysisSubmit`'s own ref.
   */
  idempotencyKey: string;
}

/**
 * Submits a `video_analysis` job directly — deliberately not
 * `useGenerationSubmit`, which always creates a `Draft` first. A draft is the
 * thing `/publish/[draftId]` and the job page's "去发布" button hang off;
 * this operation never produces a publishable asset, so a draft here would
 * just be dead weight the user's draft list would have to carry forever.
 */
export function submitVideoAnalysis(input: VideoAnalysisSubmitInput): Promise<GenerationJob> {
  return api.post<GenerationJob>(
    '/v1/generation-jobs',
    {
      operation: 'video_analysis',
      quality_tier: input.qualityTier,
      params: {
        prompt: input.notes,
        reference_asset_ids: [input.referenceAssetId],
      },
      max_credits: input.maxCredits,
    },
    { idempotencyKey: input.idempotencyKey },
  );
}

export function cancelVideoAnalysis(jobId: string): Promise<GenerationJob> {
  return api.post<GenerationJob>(`/v1/generation-jobs/${jobId}/cancel`);
}

export function listVideoAnalysisJobs(limit = 30): Promise<Page<GenerationJob>> {
  return api.get<Page<GenerationJob>>('/v1/generation-jobs', {
    query: { operation: 'video_analysis', limit },
  });
}
