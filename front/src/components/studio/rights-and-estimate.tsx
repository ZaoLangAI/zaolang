'use client';

import { useTranslations } from 'next-intl';

import { Button } from '@/components/ui/button';
import { IconClock } from '@/components/ui/icons';
import { ErrorNotice } from '@/components/ui/primitives';
import { useRouter } from '@/i18n/navigation';
import type { Quote } from '@/lib/api/types';

/**
 * The rights-confirmation checkbox, the estimated-time/price box, and the
 * quote-failed/insufficient-credit/generic error notices below it — the
 * bottom of every params panel, identical for image, video and audio.
 */
export function RightsAndEstimate({
  rightsConfirmed,
  onRightsChange,
  quote,
  quoteFailed,
  estimate,
  price,
  error,
}: {
  rightsConfirmed: boolean;
  onRightsChange: (checked: boolean) => void;
  quote: Quote | null;
  quoteFailed: boolean;
  estimate: string;
  price: string;
  error: string | null;
}) {
  const t = useTranslations('remixPage');
  const tCredits = useTranslations('credits');
  const router = useRouter();

  return (
    <>
      <label className="flex cursor-pointer items-start gap-2.5 text-xs leading-relaxed">
        <input
          type="checkbox"
          checked={rightsConfirmed}
          onChange={(event) => onRightsChange(event.target.checked)}
          className="mt-0.5 size-4 shrink-0 accent-[var(--primary)]"
        />
        {t('rightsConfirm')}
      </label>

      {quoteFailed ? (
        <ErrorNotice title={t('quoteFailed')} />
      ) : (
        <div className="flex items-center justify-between gap-3 rounded-[var(--radius-sm)] border border-border bg-surface-soft px-3 py-2.5">
          <div>
            <p className="flex items-center gap-1.5 text-xs">
              <IconClock className="size-3.5 text-muted" />
              {estimate}
            </p>
            <p className="mt-0.5 text-[11px] text-muted">{t('estimateHint')}</p>
          </div>
          <p className="tabular shrink-0 text-sm font-semibold text-amber">{price}</p>
        </div>
      )}

      {quote && !quote.sufficient ? (
        <ErrorNotice
          title={tCredits('insufficient')}
          action={
            <Button size="sm" variant="secondary" onClick={() => router.push('/billing')}>
              {tCredits('manage')}
            </Button>
          }
        />
      ) : null}

      {error ? <ErrorNotice title={error} /> : null}
    </>
  );
}
