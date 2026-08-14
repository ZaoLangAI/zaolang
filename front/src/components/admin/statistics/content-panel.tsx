'use client';

import { useTranslations } from 'next-intl';

import { TrendChart } from '@/components/admin/statistics/trend-chart';
import { DuplicateGroups } from '@/components/admin/moderation/duplicate-groups';
import type { ContentTimeseries } from '@/lib/api/admin-types';

export function ContentPanel({ timeseries }: { timeseries: ContentTimeseries }) {
  const t = useTranslations('adminStatistics');

  return (
    <div className="flex flex-col gap-6">
      <section>
        <h2 className="mb-3 text-sm font-semibold">{t('contentChartTitle')}</h2>
        <div className="rounded-[var(--radius-md)] border border-border bg-surface p-4">
          <TrendChart
            data={timeseries.points ?? []}
            emptyTitle={t('chartEmpty')}
            series={[
              { dataKey: 'published_works', label: t('contentChartPublished'), color: 'primary' },
              { dataKey: 'remix_edges', label: t('contentChartRemix'), color: 'success' },
            ]}
          />
        </div>
      </section>

      <DuplicateGroups />
    </div>
  );
}
