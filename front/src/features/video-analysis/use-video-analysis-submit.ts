'use client';

import { useTranslations } from 'next-intl';
import { useEffect, useRef, useState } from 'react';

import { useSession } from '@/components/auth/session-provider';
import * as videoAnalysisApi from '@/features/video-analysis/api';
import { ApiError } from '@/lib/api/errors';
import type { GenerationJob, QualityTier, Quote } from '@/lib/api/types';

const QUOTE_DEBOUNCE_MS = 250;

export interface VideoAnalysisSubmit {
  quote: Quote | null;
  quoteFailed: boolean;
  submitting: boolean;
  error: string | null;
  submit: (input: { referenceAssetId: string; notes: string }) => void;
}

/**
 * Quoting and submitting a `video_analysis` job — a stripped-down sibling of
 * `useGenerationSubmit` (see that hook's own doc comment) rather than a
 * caller of it, because this operation has no draft, no aspect ratio, no
 * duration and no `/jobs/[jobId]` destination: a successful submit always
 * hands the job back to the caller instead of navigating away, so the
 * studio can stream its progress inline.
 */
export function useVideoAnalysisSubmit(
  qualityTier: QualityTier,
  onSubmitted: (job: GenerationJob) => void,
): VideoAnalysisSubmit {
  const t = useTranslations('videoAnalysisPage');
  const tStates = useTranslations('states');
  const { requireAuth, status: sessionStatus } = useSession();

  const [quote, setQuote] = useState<Quote | null>(null);
  const [quoteFailed, setQuoteFailed] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const latestQuote = useRef(0);
  useEffect(() => {
    if (sessionStatus !== 'authenticated') return;
    const ticket = ++latestQuote.current;
    const timer = setTimeout(() => {
      void videoAnalysisApi
        .quoteVideoAnalysis(qualityTier)
        .then((body) => {
          if (ticket !== latestQuote.current) return;
          setQuote(body);
          setQuoteFailed(false);
        })
        .catch(() => {
          if (ticket !== latestQuote.current) return;
          setQuoteFailed(true);
        });
    }, QUOTE_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [qualityTier, sessionStatus]);

  const submit = ({ referenceAssetId, notes }: { referenceAssetId: string; notes: string }) =>
    requireAuth({
      label: t('title'),
      run: async () => {
        setSubmitting(true);
        setError(null);
        try {
          const job = await videoAnalysisApi.submitVideoAnalysis({
            qualityTier,
            referenceAssetId,
            notes,
          });
          onSubmitted(job);
        } catch (caught) {
          setError(caught instanceof ApiError ? caught.message : tStates('errorHint'));
        } finally {
          setSubmitting(false);
        }
      },
    });

  return { quote, quoteFailed, submitting, error, submit };
}
