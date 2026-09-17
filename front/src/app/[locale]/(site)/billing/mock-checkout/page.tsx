'use client';

import { useLocale, useTranslations } from 'next-intl';
import { useSearchParams } from 'next/navigation';
import { useEffect, useState } from 'react';

import { Button } from '@/components/ui/button';
import { ErrorNotice, PageHeading, StatTile } from '@/components/ui/primitives';
import { Spinner } from '@/components/ui/spinner';
import { Link, useRouter } from '@/i18n/navigation';
import type { Locale } from '@/i18n/routing';
import { api } from '@/lib/api/client';
import { isApiError } from '@/lib/api/errors';
import type { CheckoutConfirmResult, CheckoutIntent } from '@/lib/api/types';
import { formatCount } from '@/lib/format';

/**
 * `/billing/mock-checkout`: stands in for a real payment provider's hosted
 * checkout page. `credit-packages.tsx` opens this in a new tab after
 * `POST /v1/credits/checkout`; this page reads the intent back, lets the
 * user "pay", and calls `POST /v1/credits/checkout/confirm` — the client
 * cannot hold the webhook's HMAC secret, so it can never call the webhook
 * route directly.
 */
export default function MockCheckoutPage() {
  const t = useTranslations('mockCheckoutPage');
  const locale = useLocale() as Locale;
  const router = useRouter();
  const searchParams = useSearchParams();
  const ref = searchParams.get('ref');

  const [phase, setPhase] = useState<'loading' | 'ready' | 'confirming' | 'done' | 'error'>(
    ref ? 'loading' : 'error',
  );
  const [error, setError] = useState<string | null>(ref ? null : t('missingRef'));
  const [intent, setIntent] = useState<CheckoutIntent | null>(null);
  const [result, setResult] = useState<CheckoutConfirmResult | null>(null);

  useEffect(() => {
    if (!ref) return;
    let cancelled = false;
    api
      .get<CheckoutIntent>(`/v1/credits/checkout/${encodeURIComponent(ref)}`)
      .then((data) => {
        if (cancelled) return;
        setIntent(data);
        setPhase(data.status === 'succeeded' ? 'done' : 'ready');
      })
      .catch((caught: unknown) => {
        if (cancelled) return;
        setPhase('error');
        setError(
          isApiError(caught) && caught.isNotFound
            ? t('notFound')
            : isApiError(caught) && caught.isForbidden
              ? t('forbidden')
              : isApiError(caught)
                ? caught.message
                : t('loadFailed'),
        );
      });
    return () => {
      cancelled = true;
    };
    // Reruns only if the ref itself changes; the fetch handles its own
    // cancellation on unmount instead of being re-triggered by `t`.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ref]);

  const confirm = async () => {
    if (!ref) return;
    setPhase('confirming');
    setError(null);
    try {
      const confirmed = await api.post<CheckoutConfirmResult>('/v1/credits/checkout/confirm', {
        external_reference: ref,
      });
      setResult(confirmed);
      setPhase('done');
    } catch (caught) {
      setPhase('ready');
      setError(isApiError(caught) ? caught.message : t('confirmFailed'));
    }
  };

  const money = intent
    ? new Intl.NumberFormat(locale, {
        style: 'currency',
        currency: intent.currency,
        minimumFractionDigits: intent.currency === 'JPY' ? 0 : 2,
      }).format(intent.currency === 'JPY' ? intent.amount_minor : intent.amount_minor / 100)
    : null;
  const totalCredits = intent ? intent.credits + intent.bonus_credits : 0;

  return (
    <div className="mx-auto flex w-full max-w-[560px] flex-col items-center gap-6 px-4 py-16 text-center">
      <PageHeading eyebrow={t('eyebrow')} title={t('title')} description={t('subtitle')} />

      {phase === 'loading' ? <Spinner label={t('loading')} /> : null}

      {phase === 'error' ? (
        <ErrorNotice
          title={error ?? t('loadFailed')}
          action={
            <Button variant="secondary" onClick={() => router.push('/billing')}>
              {t('backToBilling')}
            </Button>
          }
        />
      ) : null}

      {(phase === 'ready' || phase === 'confirming') && intent ? (
        <div className="flex w-full flex-col gap-4 rounded-[var(--radius-md)] border border-border bg-surface p-6">
          <div className="grid grid-cols-2 divide-x divide-border overflow-hidden rounded-[var(--radius-sm)] border border-border">
            <StatTile value={money ?? ''} label={t('amountLabel')} />
            <StatTile value={formatCount(totalCredits, locale)} label={t('creditsLabel')} />
          </div>
          <p className="text-xs text-muted">{t('mockNotice')}</p>
          {error ? <ErrorNotice title={error} /> : null}
          <div className="flex justify-center gap-3">
            <Link href="/billing">
              <Button variant="secondary">{t('cancel')}</Button>
            </Link>
            <Button loading={phase === 'confirming'} onClick={() => void confirm()}>
              {t('confirmButton')}
            </Button>
          </div>
        </div>
      ) : null}

      {phase === 'done' ? (
        <div className="flex w-full flex-col items-center gap-4 rounded-[var(--radius-md)] border border-border bg-surface p-6">
          <p className="text-lg font-semibold text-success">{t('succeeded')}</p>
          <p className="text-sm text-muted">
            {result
              ? t('succeededHint', { balance: formatCount(result.available_balance, locale) })
              : t('alreadySettled')}
          </p>
          <Button onClick={() => router.push('/billing')}>{t('backToBilling')}</Button>
        </div>
      ) : null}
    </div>
  );
}
