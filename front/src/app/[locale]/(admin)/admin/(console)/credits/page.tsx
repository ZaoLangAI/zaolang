import { getLocale, getTranslations } from 'next-intl/server';

import { DanglingReserves } from '@/components/admin/credits/dangling-reserves';
import { LedgerConsole } from '@/components/admin/credits/ledger-console';
import { RedemptionCodesPanel } from '@/components/admin/credits/redemption-codes-panel';
import { PageHeading, StatTile } from '@/components/ui/primitives';
import type { Locale } from '@/i18n/routing';
import { adminFetch } from '@/lib/api/admin-server';
import type { Reconciliation } from '@/lib/api/admin-types';
import { formatDateTime, formatNumber } from '@/lib/format';

export async function generateMetadata() {
  const t = await getTranslations('adminCredits');
  return { title: t('title') };
}

export default async function AdminCreditsPage() {
  const t = await getTranslations('adminCredits');
  const locale = (await getLocale()) as Locale;

  const report = await adminFetch<Reconciliation>('/v1/admin/credits/reconciliation');

  return (
    <div className="flex flex-col gap-6">
      <PageHeading title={t('title')} description={t('subtitle')} />

      <section>
        <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="text-sm font-semibold">{t('reconciliation')}</h2>
          <p className="text-xs text-muted">
            {t('generatedAt', { at: formatDateTime(report.generated_at, locale) })}
          </p>
        </div>
        <ul className="grid gap-3 sm:grid-cols-3">
          <li className="rounded-[var(--radius-md)] border border-border bg-surface">
            <StatTile value={formatNumber(report.account_count, locale)} label={t('accounts')} />
          </li>
          <li className="rounded-[var(--radius-md)] border border-border bg-surface">
            <StatTile
              value={formatNumber(report.mismatched_account_count, locale)}
              label={t('mismatched')}
              hint={t('mismatchedHint')}
              tone={report.mismatched_account_count > 0 ? 'danger' : 'success'}
            />
          </li>
          <li className="rounded-[var(--radius-md)] border border-border bg-surface">
            <StatTile
              value={formatNumber(report.dangling_reserved_count, locale)}
              label={t('dangling')}
              hint={t('danglingHint')}
              tone={report.dangling_reserved_count > 0 ? 'amber' : 'success'}
            />
          </li>
        </ul>
      </section>

      <DanglingReserves />
      <RedemptionCodesPanel />
      <LedgerConsole />
    </div>
  );
}
