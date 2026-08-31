'use client';

import { useLocale, useTranslations } from 'next-intl';
import { useEffect, useState } from 'react';

import { OptionGroup } from '@/components/studio/option-group';
import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { ErrorNotice } from '@/components/ui/primitives';
import type { Locale } from '@/i18n/routing';
import { api, newIdempotencyKey } from '@/lib/api/client';
import { isApiError } from '@/lib/api/errors';
import type { GenerationJob, Quote } from '@/lib/api/types';
import { formatCount } from '@/lib/format';

const PROMOTE_TIERS = ['standard', 'cinematic'] as const;
type PromoteTier = (typeof PROMOTE_TIERS)[number];

/**
 * "升级为标准/电影档" — offered on a succeeded `preview`-tier job (job page
 * and the image studio's inline result alike). `POST .../promote` always
 * reserves a *new* job's credits rather than topping up the preview's own
 * reservation (see the route's own doc comment), so this dialog quotes the
 * chosen tier first and sends that quote back as `max_credits` — the same
 * guard every other submit path uses to refuse rather than silently pay
 * more than what was shown.
 */
export function PromoteJobDialog({
  open,
  onClose,
  job,
  onPromoted,
}: {
  open: boolean;
  onClose: () => void;
  job: GenerationJob;
  onPromoted: (job: GenerationJob) => void;
}) {
  const t = useTranslations('jobPage');
  const tActions = useTranslations('actions');
  const locale = useLocale() as Locale;

  const [tier, setTier] = useState<PromoteTier>('standard');
  const [quote, setQuote] = useState<Quote | null>(null);
  const [quoting, setQuoting] = useState(false);
  const [quoteFailed, setQuoteFailed] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Reset for the next open, computed during render rather than in an
  // effect — `wasOpen` is the only piece of derived-from-props state this
  // needs, so there's no separate mount-then-reset render to cascade
  // through (same "adjust state during render" pattern `command-palette.tsx`
  // uses for its own open-signal reset).
  const [wasOpen, setWasOpen] = useState(open);
  if (open !== wasOpen) {
    setWasOpen(open);
    if (open) {
      setTier('standard');
      setError(null);
    }
  }

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    void (async () => {
      // Yield first so the loading-state flip is not a synchronous setState
      // inside the effect body — same deferral `image-generation-studio.tsx`
      // uses before its own post-mount resets.
      await Promise.resolve();
      if (cancelled) return;
      setQuoting(true);
      setQuoteFailed(false);
      try {
        const body = await api.post<Quote>('/v1/generation-jobs/quote', {
          operation: job.operation,
          quality_tier: tier,
          duration_seconds: job.duration_seconds ?? 0,
          asset_kind: job.asset_kind ?? 'general',
          character_views: job.character_views ?? null,
        });
        if (cancelled) return;
        setQuote(body);
      } catch {
        if (!cancelled) setQuoteFailed(true);
      } finally {
        if (!cancelled) setQuoting(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open, tier, job.operation, job.asset_kind, job.character_views, job.duration_seconds]);

  const promote = async () => {
    if (!quote) return;
    setSubmitting(true);
    setError(null);
    try {
      const promoted = await api.post<GenerationJob>(
        `/v1/generation-jobs/${job.id}/promote`,
        { quality_tier: tier, max_credits: quote.credits },
        // A one-shot dialog: reopening after a failed attempt is a fresh
        // click, so a fresh key here is correct rather than P0-2's reuse.
        { idempotencyKey: newIdempotencyKey() },
      );
      onPromoted(promoted);
      onClose();
    } catch (caught) {
      setError(isApiError(caught) ? caught.message : t('promoteFailed'));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog
      open={open}
      onClose={() => {
        if (!submitting) onClose();
      }}
      title={t('promoteTitle')}
      size="sm"
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={submitting}>
            {tActions('cancel')}
          </Button>
          <Button
            loading={submitting}
            disabled={quoting || !quote || (quote && !quote.sufficient)}
            onClick={() => void promote()}
          >
            {t('promoteConfirm')}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <p className="text-xs text-muted">{t('promoteHint')}</p>
        <OptionGroup
          label={t('promoteTierLabel')}
          value={tier}
          onChange={setTier}
          columns={2}
          options={PROMOTE_TIERS.map((value) => ({
            value,
            label: value === 'standard' ? t('promoteTierStandard') : t('promoteTierCinematic'),
            trailing:
              quote && tier === value ? t('promoteTierCredits', { count: formatCount(quote.credits, locale) }) : undefined,
          }))}
        />
        {quoteFailed ? <ErrorNotice title={t('quoteFailed')} /> : null}
        {quote && !quote.sufficient ? <ErrorNotice title={t('promoteInsufficientCredits')} /> : null}
        {error ? <ErrorNotice title={error} /> : null}
      </div>
    </Dialog>
  );
}
