'use client';

import { useTranslations } from 'next-intl';
import { useEffect, useRef, useState } from 'react';

import { useSession } from '@/components/auth/session-provider';
import { useRouter } from '@/i18n/navigation';
import { api, newIdempotencyKey } from '@/lib/api/client';
import { ApiError } from '@/lib/api/errors';
import type { Draft, GenerationJob, Operation, QualityTier, Quote } from '@/lib/api/types';

/** The three inputs the price depends on. */
export interface GenerationQuoteInput {
  operation: Operation;
  qualityTier: QualityTier;
  durationSeconds: number;
}

export interface GenerationSubmitInput extends GenerationQuoteInput {
  prompt: string;
  aspectRatio: string;
  referenceAssetIds: string[];
  /** Cast picked from the character library; merged server-side into the job's
   * reference images and voice hints (see `characters.service.apply_character_refs`). */
  characterIds?: string[];
  /** Free-form provider hints, e.g. `{ sound: true }`. */
  extra?: Record<string, unknown>;
  /** A licensed remix source. Carried by both the draft and the job. */
  sourceWorkId?: string;
  /** Ceiling sent to the API; the job is refused rather than trimmed. */
  maxCredits?: number;
  draftTitle?: string | null;
  /**
   * Names a `shortform.profiles` entry. The API refuses the job when it
   * contradicts the aspect ratio or the duration, so it travels with them.
   */
  shortformProfile?: string;
  /**
   * Extra keys merged into the draft's params.
   *
   * The draft is the only thing that outlives the job, so anything the steps
   * after generation need — a caption written while framing the shot, say — has
   * to be stored on it rather than in component state.
   */
  draftParams?: Record<string, unknown>;
}

export interface GenerationSubmit {
  quote: Quote | null;
  /** The quote call failed; the estimate on screen is stale or absent. */
  quoteFailed: boolean;
  submitting: boolean;
  error: string | null;
  /** Field paths from a 422, so a shell can show them next to the control. */
  fieldErrors: Record<string, string>;
  /** Goes through the login wall, then creates the draft and the job. */
  submit: (input: GenerationSubmitInput) => void;
}

const QUOTE_DEBOUNCE_MS = 250;

/**
 * Quoting and submitting a generation, shared by every studio shell.
 *
 * `/create/new` and `/remix/[workId]` deliberately share one component so the
 * remix path cannot drift from the create path. A shell whose layout differs
 * too much to share the component still has to share *this*: the debounce, the
 * login wall, the draft, the idempotency key and the destination are the parts
 * that would drift silently and expensively.
 */
export function useGenerationSubmit(
  quoteInput: GenerationQuoteInput,
  { label }: { label: string },
): GenerationSubmit {
  const tStates = useTranslations('states');
  const router = useRouter();
  const { requireAuth, status: sessionStatus } = useSession();

  const [quote, setQuote] = useState<Quote | null>(null);
  const [quoteFailed, setQuoteFailed] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  const { operation, qualityTier, durationSeconds } = quoteInput;

  // Re-quote whenever a priced input changes. Debounced because the tier and
  // duration controls are adjacent and users sweep across them.
  const latestQuote = useRef(0);
  useEffect(() => {
    if (sessionStatus !== 'authenticated') return;
    const ticket = ++latestQuote.current;
    const timer = setTimeout(() => {
      void api
        .post<Quote>('/v1/generation-jobs/quote', {
          operation,
          quality_tier: qualityTier,
          duration_seconds: durationSeconds,
        })
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
  }, [operation, qualityTier, durationSeconds, sessionStatus]);

  /**
   * Kept across a failed attempt so a retry reuses the same draft instead of
   * leaving a trail of empty ones in the user's library. Cleared as soon as a
   * job is attached to it.
   */
  const pendingDraft = useRef<string | null>(null);

  const submit = (input: GenerationSubmitInput) =>
    requireAuth({
      label,
      run: async () => {
        setSubmitting(true);
        setError(null);
        setFieldErrors({});
        try {
          // The draft is what `/publish/[draftId]` and the job page's publish
          // button hang off; a job submitted without one produces a result the
          // user cannot publish.
          if (pendingDraft.current === null) {
            const draft = await api.post<Draft>('/v1/drafts', {
              source_work_id: input.sourceWorkId ?? null,
              title: input.draftTitle ?? null,
              params: {
                prompt: input.prompt,
                aspect_ratio: input.aspectRatio,
                duration_seconds: input.durationSeconds,
                operation: input.operation,
                quality_tier: input.qualityTier,
                ...(input.shortformProfile
                  ? { shortform_profile: input.shortformProfile }
                  : undefined),
                ...input.draftParams,
              },
            });
            pendingDraft.current = draft.id;
          }

          const job = await api.post<GenerationJob>(
            '/v1/generation-jobs',
            {
              operation: input.operation,
              quality_tier: input.qualityTier,
              draft_id: pendingDraft.current,
              source_work_id: input.sourceWorkId,
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
            // One key per intent: a retried submit must not create a second job.
            { idempotencyKey: newIdempotencyKey() },
          );
          pendingDraft.current = null;
          router.push(`/jobs/${job.id}`);
        } catch (caught) {
          setError(caught instanceof ApiError ? caught.message : tStates('errorHint'));
          if (caught instanceof ApiError) setFieldErrors(caught.fieldErrors);
          setSubmitting(false);
        }
      },
    });

  return { quote, quoteFailed, submitting, error, fieldErrors, submit };
}
