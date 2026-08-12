'use client';

import { useState } from 'react';

import { useSession } from '@/components/auth/session-provider';
import { api, newIdempotencyKey } from '@/lib/api/client';
import { ApiError } from '@/lib/api/errors';
import type { Draft, GenerationJob, Operation, QualityTier } from '@/lib/api/types';

export interface PreviewGenerationInput {
  operation: Operation;
  durationSeconds: number;
  prompt: string;
  aspectRatio: string;
  referenceAssetIds: string[];
  characterIds?: string[];
  extra?: Record<string, unknown>;
  shortformProfile?: string;
  draftTitle?: string | null;
  draftParams?: Record<string, unknown>;
  maxCredits?: number;
}

export interface PreviewBatchOutcome {
  jobs: GenerationJob[];
  /** How many of the requested candidates could not be submitted — most
   * often insufficient balance partway through the batch. There is no
   * shared reservation across the batch, so a partial result is expected
   * rather than treated as a hard failure. */
  failed: number;
}

/**
 * Preview-then-promote submission, kept separate from `useGenerationSubmit`.
 *
 * That hook is shared with `/create/new` and `/remix/[workId]` and assumes
 * exactly one job per draft lifecycle (it clears its pending draft the
 * instant a job is created). This flow needs several jobs against the same
 * draft before one of them is promoted, so it owns its own draft handle
 * instead of reusing the shared hook's private one.
 */
export function usePreviewGeneration() {
  const { requireAuth } = useSession();
  const [batchPending, setBatchPending] = useState(false);
  const [batchError, setBatchError] = useState<string | null>(null);
  const [promoting, setPromoting] = useState(false);
  const [promoteError, setPromoteError] = useState<string | null>(null);

  const ensureDraft = async (input: PreviewGenerationInput): Promise<string> => {
    const draft = await api.post<Draft>('/v1/drafts', {
      title: input.draftTitle ?? null,
      params: {
        prompt: input.prompt,
        aspect_ratio: input.aspectRatio,
        duration_seconds: input.durationSeconds,
        operation: input.operation,
        quality_tier: 'preview',
        ...(input.shortformProfile ? { shortform_profile: input.shortformProfile } : undefined),
        ...input.draftParams,
      },
    });
    return draft.id;
  };

  const submitOnePreview = (draftId: string, input: PreviewGenerationInput) =>
    api.post<GenerationJob>(
      '/v1/generation-jobs',
      {
        operation: input.operation,
        quality_tier: 'preview',
        draft_id: draftId,
        params: {
          prompt: input.prompt,
          aspect_ratio: input.aspectRatio,
          duration_seconds: input.durationSeconds,
          reference_asset_ids: input.referenceAssetIds,
          character_ids: input.characterIds ?? [],
          shortform_profile: input.shortformProfile,
          extra: input.extra ?? {},
        },
        max_credits: input.maxCredits,
      },
      { idempotencyKey: newIdempotencyKey() },
    );

  /** Resolves once every candidate has either succeeded or failed to
   * *submit* — it does not wait for generation to finish. The caller polls
   * the returned jobs (e.g. via `useJobStream`) for that. */
  const submitPreviewBatch = (
    draftId: string,
    input: PreviewGenerationInput,
    count: number,
  ): Promise<PreviewBatchOutcome> =>
    new Promise((resolve) => {
      requireAuth({
        label: input.prompt,
        run: async () => {
          setBatchPending(true);
          setBatchError(null);
          const settled = await Promise.allSettled(
            Array.from({ length: count }, () => submitOnePreview(draftId, input)),
          );
          const jobs = settled
            .filter((item): item is PromiseFulfilledResult<GenerationJob> => item.status === 'fulfilled')
            .map((item) => item.value);
          const failed = settled.length - jobs.length;
          if (jobs.length === 0) {
            const firstFailure = settled.find(
              (item): item is PromiseRejectedResult => item.status === 'rejected',
            );
            setBatchError(
              firstFailure?.reason instanceof ApiError ? firstFailure.reason.message : null,
            );
          }
          setBatchPending(false);
          resolve({ jobs, failed });
        },
      });
    });

  const promote = async (
    jobId: string,
    qualityTier: Exclude<QualityTier, 'preview'>,
    maxCredits?: number,
  ): Promise<GenerationJob | null> => {
    setPromoting(true);
    setPromoteError(null);
    try {
      return await api.post<GenerationJob>(
        `/v1/generation-jobs/${jobId}/promote`,
        { quality_tier: qualityTier, max_credits: maxCredits },
        { idempotencyKey: newIdempotencyKey() },
      );
    } catch (caught) {
      setPromoteError(caught instanceof ApiError ? caught.message : null);
      return null;
    } finally {
      setPromoting(false);
    }
  };

  return {
    ensureDraft,
    submitPreviewBatch,
    batchPending,
    batchError,
    promote,
    promoting,
    promoteError,
  };
}
