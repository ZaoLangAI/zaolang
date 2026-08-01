import { getLocale, getTranslations } from 'next-intl/server';

import { SignInPrompt } from '@/components/auth/sign-in-prompt';
import { CreditPackages } from '@/components/billing/credit-packages';
import { LedgerTable } from '@/components/billing/ledger-table';
import { PageHeading, StatTile } from '@/components/ui/primitives';
import type { Locale } from '@/i18n/routing';
import { serverFetchOrNull } from '@/lib/api/server';
import type { CreditPackage, LedgerEntry, Me, Page, Region } from '@/lib/api/types';
import { formatCount } from '@/lib/format';

export async function generateMetadata() {
  const t = await getTranslations('billingPage');
  return { title: t('title'), description: t('subtitle') };
}

export default async function BillingPage() {
  const t = await getTranslations('billingPage');
  const locale = (await getLocale()) as Locale;

  const me = await serverFetchOrNull<Me>('/v1/auth/me', { authenticated: true });
  if (!me) return <SignInPrompt />;

  const [packages, ledger] = await Promise.all([
    serverFetchOrNull<Page<CreditPackage>>('/v1/credits/packages', {
      authenticated: true,
      query: { region: me.region },
    }),
    serverFetchOrNull<Page<LedgerEntry>>('/v1/credits/ledger', {
      authenticated: true,
      query: { limit: 50 },
    }),
  ]);

  return (
    <div className="mx-auto flex w-full max-w-[1160px] flex-col gap-6 px-4 py-8 sm:px-6">
      <PageHeading eyebrow={t('eyebrow')} title={t('title')} description={t('subtitle')} />

      <div className="grid grid-cols-2 divide-x divide-border overflow-hidden rounded-[var(--radius-md)] border border-border bg-surface">
        <StatTile value={formatCount(me.available_credits, locale)} label={t('available')} />
        <StatTile value={formatCount(me.reserved_credits, locale)} label={t('reserved')} />
      </div>
      <p className="-mt-4 text-xs text-muted">{t('reservedHint')}</p>

      <CreditPackages packages={packages?.items ?? []} region={me.region as Region} />
      <LedgerTable entries={ledger?.items ?? []} />
    </div>
  );
}
