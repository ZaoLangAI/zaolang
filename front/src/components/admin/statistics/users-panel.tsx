'use client';

import { useLocale, useTranslations } from 'next-intl';

import { TrendChart } from '@/components/admin/statistics/trend-chart';
import { StatTile } from '@/components/ui/primitives';
import type { Locale } from '@/i18n/routing';
import type { UserGrowthTimeseries } from '@/lib/api/admin-types';
import { formatNumber } from '@/lib/format';

export function UsersPanel({ timeseries }: { timeseries: UserGrowthTimeseries }) {
  const t = useTranslations('adminStatistics');
  const locale = useLocale() as Locale;

  return (
    <div className="flex flex-col gap-6">
      <section>
        <ul className="grid gap-3 sm:grid-cols-2">
          <li className="rounded-[var(--radius-md)] border border-border bg-surface">
            <StatTile
              value={formatNumber(timeseries.total_users, locale)}
              label={t('totalUsers')}
            />
          </li>
          <li className="rounded-[var(--radius-md)] border border-border bg-surface">
            <StatTile
              value={formatNumber(timeseries.suspended_users, locale)}
              label={t('suspendedUsers')}
              tone={timeseries.suspended_users > 0 ? 'amber' : 'success'}
            />
          </li>
        </ul>
      </section>

      <section>
        <h2 className="mb-3 text-sm font-semibold">{t('usersChartTitle')}</h2>
        <div className="rounded-[var(--radius-md)] border border-border bg-surface p-4">
          <TrendChart
            data={timeseries.points ?? []}
            emptyTitle={t('chartEmpty')}
            series={[
              { dataKey: 'new_users', label: t('usersChartNewUsers'), color: 'primary' },
            ]}
          />
        </div>
      </section>
    </div>
  );
}
