'use client';

import { useLocale, useTranslations } from 'next-intl';
import { useState } from 'react';

import { Button } from '@/components/ui/button';
import { IconSparkle } from '@/components/ui/icons';
import { Badge, EmptyState, SectionHeading } from '@/components/ui/primitives';
import { useToast } from '@/components/ui/toast';
import type { Locale, Region } from '@/i18n/routing';
import { api, newIdempotencyKey } from '@/lib/api/client';
import type { CreditPackage } from '@/lib/api/types';
import { formatCount, formatMoney } from '@/lib/format';

interface Checkout {
  checkout_url: string;
}

export function CreditPackages({
  packages,
  region,
}: {
  packages: CreditPackage[];
  region: Region;
}) {
  const t = useTranslations('billingPage');
  const locale = useLocale() as Locale;
  const { notify } = useToast();
  const [busy, setBusy] = useState<string | null>(null);

  const buy = async (pack: CreditPackage) => {
    setBusy(pack.id);
    try {
      const checkout = await api.post<Checkout>(
        '/v1/credits/checkout',
        { package_id: pack.id },
        { idempotencyKey: newIdempotencyKey() },
      );
      notify(t('checkoutOpened'), 'success');
      // Opened rather than navigated: the ledger below should still be here
      // when the user comes back from the payment page.
      window.open(checkout.checkout_url, '_blank', 'noopener');
    } catch {
      notify(t('buyFailed'), 'error');
    } finally {
      setBusy(null);
    }
  };

  return (
    <section>
      <SectionHeading title={t('packages')} description={t('packagesHint')} />
      {packages.length === 0 ? (
        <EmptyState title={t('ledgerEmpty')} />
      ) : (
        <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {packages.map((pack) => (
            <li
              key={pack.id}
              className="flex flex-col rounded-[var(--radius-md)] border border-border bg-surface p-5"
            >
              <p className="tabular flex items-center gap-2 text-xl font-semibold">
                <IconSparkle className="size-5 text-amber" />
                {t('packageCredits', { count: formatCount(pack.credits, locale) })}
              </p>
              {pack.bonus_credits > 0 ? (
                <p className="mt-2">
                  <Badge tone="success">
                    {t('bonus', { count: formatCount(pack.bonus_credits, locale) })}
                  </Badge>
                </p>
              ) : null}
              <p className="tabular mt-4 flex-1 text-lg">
                {formatMoney(pack.price_minor, region, locale)}
              </p>
              <Button
                className="mt-4"
                loading={busy === pack.id}
                onClick={() => void buy(pack)}
                fullWidth
              >
                {t('buy')}
              </Button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
