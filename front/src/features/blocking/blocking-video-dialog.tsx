'use client';

import { useLocale, useTranslations } from 'next-intl';
import { useEffect, useMemo, useState } from 'react';

import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { Select } from '@/components/ui/field';
import { ErrorNotice } from '@/components/ui/primitives';
import { Spinner } from '@/components/ui/spinner';
import type { Locale } from '@/i18n/routing';
import { api } from '@/lib/api/client';
import type { QualityTier } from '@/lib/api/types';
import { formatCount } from '@/lib/format';

import type { SegmentVideoParams } from './use-blocking-video';
import type { SegmentVideoPlan } from './video-plan';

const TIERS: QualityTier[] = ['preview', 'standard', 'cinematic'];
const RESOLUTIONS: SegmentVideoParams['resolution'][] = ['720p', '1080p', '2K'];

interface QuoteResult {
  items: Array<{ unit_credits: number; count: number; credits: number }>;
  total_credits: number;
  period_remaining: number | null;
  within_spend_limit: boolean;
  sufficient: boolean;
}

interface Quote {
  total: number;
  unitByKey: Record<string, number>;
  sufficient: boolean;
  withinSpendLimit: boolean;
  periodRemaining: number | null;
}

/** Segments differ in length, so the quote is one `quote:batch` line per
 * distinct duration — the same `quote_for` a submit uses, never a range. */
async function quoteSegments(plans: SegmentVideoPlan[], tier: QualityTier): Promise<Quote> {
  const durations = [...new Set(plans.map((plan) => plan.durationSeconds))];
  const result = await api.post<QuoteResult>('/v1/generation-jobs/quote:batch', {
    items: durations.map((duration) => ({
      operation: 'text_to_video',
      quality_tier: tier,
      duration_seconds: duration,
      count: plans.filter((plan) => plan.durationSeconds === duration).length,
    })),
  });
  const unitByDuration = new Map(
    durations.map((duration, index) => [duration, result.items[index]?.unit_credits ?? 0]),
  );
  return {
    total: result.total_credits,
    unitByKey: Object.fromEntries(
      plans.map((plan) => [plan.key, unitByDuration.get(plan.durationSeconds) ?? 0]),
    ),
    sufficient: result.sufficient,
    withinSpendLimit: result.within_spend_limit,
    periodRemaining: result.period_remaining,
  };
}

export function BlockingVideoDialog({
  plans,
  onClose,
  onConfirm,
}: {
  plans: SegmentVideoPlan[];
  onClose: () => void;
  onConfirm: (params: SegmentVideoParams, unitCreditsByKey: Record<string, number>) => void;
}) {
  const t = useTranslations('blockingStudio');
  const tScript = useTranslations('scriptStudio');
  const tCredits = useTranslations('credits');
  const locale = useLocale() as Locale;
  const [params, setParams] = useState<SegmentVideoParams>({
    qualityTier: 'standard',
    resolution: '1080p',
  });
  const [quote, setQuote] = useState<Quote | null>(null);
  const [quoteFailed, setQuoteFailed] = useState(false);
  const unlinked = useMemo(() => [...new Set(plans.flatMap((plan) => plan.unlinkedCast))], [plans]);

  useEffect(() => {
    let cancelled = false;
    void quoteSegments(plans, params.qualityTier)
      .then((next) => {
        if (cancelled) return;
        setQuote(next);
        setQuoteFailed(false);
      })
      .catch(() => {
        if (cancelled) return;
        setQuote(null);
        setQuoteFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [plans, params.qualityTier]);

  const quoting = !quote && !quoteFailed;
  return (
    <Dialog
      open
      onClose={onClose}
      title={t('videoDialogTitle', { count: plans.length })}
      description={t('videoDialogHint')}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            {t('cancel')}
          </Button>
          <Button
            disabled={!quote?.sufficient || plans.length === 0}
            loading={quoting}
            onClick={() => quote && onConfirm(params, quote.unitByKey)}
          >
            {t('videoConfirm')}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        <div className="grid gap-3 sm:grid-cols-2">
          <Select
            label={tScript('batchQuality')}
            value={params.qualityTier}
            options={TIERS.map((value) => ({ value, label: tScript(`batchTier.${value}`) }))}
            onChange={(event) =>
              setParams((current) => ({
                ...current,
                qualityTier: event.target.value as QualityTier,
              }))
            }
          />
          <Select
            label={tScript('batchResolution')}
            value={params.resolution}
            options={RESOLUTIONS.map((value) => ({ value, label: value }))}
            onChange={(event) =>
              setParams((current) => ({
                ...current,
                resolution: event.target.value as SegmentVideoParams['resolution'],
              }))
            }
          />
        </div>
        {quoting ? (
          <div className="flex items-center gap-2 text-sm text-muted">
            <Spinner />
            {t('quoting')}
          </div>
        ) : null}
        {quoteFailed ? <ErrorNotice title={tScript('batchQuoteFailed')} /> : null}
        {quote && !quote.sufficient ? (
          <ErrorNotice
            title={
              quote.withinSpendLimit
                ? tScript('batchInsufficient')
                : tScript('batchSpendLimit', {
                    remaining: formatCount(quote.periodRemaining ?? 0, locale),
                  })
            }
          />
        ) : null}
        {quote ? (
          <p className="text-sm text-amber">
            {tCredits('amount', { count: formatCount(quote.total, locale) })}
          </p>
        ) : null}
        {unlinked.length > 0 ? (
          <p className="text-xs text-muted">{t('videoUnlinked', { names: unlinked.join('、') })}</p>
        ) : null}
        <ul className="max-h-48 overflow-y-auto rounded-[var(--radius-sm)] border border-border bg-surface-soft px-3 py-2 text-sm">
          {plans.map((plan) => (
            <li key={plan.key} className="flex justify-between gap-3 py-0.5">
              <span className="min-w-0 truncate">{plan.key}</span>
              <span className="shrink-0 text-muted">{plan.durationSeconds}s</span>
            </li>
          ))}
        </ul>
      </div>
    </Dialog>
  );
}
