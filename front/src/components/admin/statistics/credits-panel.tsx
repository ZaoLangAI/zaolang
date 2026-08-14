'use client';

import { useLocale, useTranslations } from 'next-intl';

import { TrendChart } from '@/components/admin/statistics/trend-chart';
import { DanglingReserves } from '@/components/admin/credits/dangling-reserves';
import { StatTile } from '@/components/ui/primitives';
import type { Locale } from '@/i18n/routing';
import type { CreditFlowTimeseries, Reconciliation } from '@/lib/api/admin-types';
import { formatDateTime, formatNumber } from '@/lib/format';

export function CreditsPanel({
  reconciliation,
  timeseries,
}: {
  reconciliation: Reconciliation;
  timeseries: CreditFlowTimeseries;
}) {
  const t = useTranslations('adminStatistics');
  const tCredits = useTranslations('adminCredits');
  const locale = useLocale() as Locale;

  return (
    <div className="flex flex-col gap-6">
      <section>
        <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="text-sm font-semibold">{t('sectionCredits')}</h2>
          <p className="text-xs text-muted">
            {tCredits('generatedAt', { at: formatDateTime(reconciliation.generated_at, locale) })}
          </p>
        </div>
        <ul className="grid gap-3 sm:grid-cols-3">
          <li className="rounded-[var(--radius-md)] border border-border bg-surface">
            <StatTile
              value={formatNumber(reconciliation.account_count, locale)}
              label={tCredits('accounts')}
            />
          </li>
          <li className="rounded-[var(--radius-md)] border border-border bg-surface">
            <StatTile
              value={formatNumber(reconciliation.mismatched_account_count, locale)}
              label={tCredits('mismatched')}
              hint={tCredits('mismatchedHint')}
              tone={reconciliation.mismatched_account_count > 0 ? 'danger' : 'success'}
            />
          </li>
          <li className="rounded-[var(--radius-md)] border border-border bg-surface">
            <StatTile
              value={formatNumber(reconciliation.dangling_reserved_count, locale)}
              label={tCredits('dangling')}
              hint={tCredits('danglingHint')}
              tone={reconciliation.dangling_reserved_count > 0 ? 'amber' : 'success'}
            />
          </li>
        </ul>
      </section>

      <section>
        <h2 className="mb-3 text-sm font-semibold">{t('creditsChartTitle')}</h2>
        <div className="rounded-[var(--radius-md)] border border-border bg-surface p-4">
          <TrendChart
            data={timeseries.points ?? []}
            emptyTitle={t('chartEmpty')}
            series={[
              { dataKey: 'granted', label: t('creditsChartGranted'), color: 'success' },
              { dataKey: 'purchased', label: t('creditsChartPurchased'), color: 'primary' },
              { dataKey: 'captured', label: t('creditsChartCaptured'), color: 'amber' },
              { dataKey: 'refunded', label: t('creditsChartRefunded'), color: 'muted' },
            ]}
          />
        </div>
        <div className="mt-3 rounded-[var(--radius-md)] border border-border bg-surface p-4">
          <TrendChart
            data={timeseries.points ?? []}
            emptyTitle={t('chartEmpty')}
            height={160}
            series={[
              { dataKey: 'royalty_out', label: t('creditsChartRoyaltyOut'), color: 'danger' },
              { dataKey: 'royalty_in', label: t('creditsChartRoyaltyIn'), color: 'success' },
            ]}
          />
        </div>
      </section>

      <DanglingReserves />
    </div>
  );
}
