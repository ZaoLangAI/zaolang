'use client';

import { useLocale, useTranslations } from 'next-intl';

import { TrendChart } from '@/components/admin/statistics/trend-chart';
import { StatTile } from '@/components/ui/primitives';
import type { Locale } from '@/i18n/routing';
import type { JobStats, JobsTimeseries } from '@/lib/api/admin-types';
import { formatNumber } from '@/lib/format';

export function JobsPanel({
  jobStats,
  timeseries,
}: {
  jobStats: JobStats;
  timeseries: JobsTimeseries;
}) {
  const t = useTranslations('adminStatistics');
  const locale = useLocale() as Locale;

  const chartData = (timeseries.points ?? []).map((point) => ({
    date: point.date,
    total: point.total,
    succeeded: point.succeeded,
    failed: point.failed,
    avg_completion_ms: point.avg_completion_ms,
  }));

  return (
    <div className="flex flex-col gap-6">
      <section>
        <h2 className="mb-3 text-sm font-semibold">{t('jobsChartTitle')}</h2>
        <div className="rounded-[var(--radius-md)] border border-border bg-surface p-4">
          <TrendChart
            data={chartData}
            emptyTitle={t('chartEmpty')}
            series={[
              { dataKey: 'total', label: t('jobsChartTotal'), color: 'muted' },
              { dataKey: 'succeeded', label: t('jobsChartSucceeded'), color: 'success' },
              { dataKey: 'failed', label: t('jobsChartFailed'), color: 'danger' },
            ]}
          />
        </div>
      </section>

      <section>
        <h2 className="mb-3 text-sm font-semibold">{t('avgCompletionChartTitle')}</h2>
        <div className="rounded-[var(--radius-md)] border border-border bg-surface p-4">
          <TrendChart
            data={chartData}
            emptyTitle={t('chartEmpty')}
            height={180}
            series={[
              { dataKey: 'avg_completion_ms', label: t('avgCompletion'), color: 'primary' },
            ]}
          />
        </div>
      </section>

      <section>
        <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="text-sm font-semibold">{t('sectionJobs')}</h2>
          <p className="text-xs text-muted">{t('windowHours', { hours: jobStats.window_hours })}</p>
        </div>
        <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <li className="rounded-[var(--radius-md)] border border-border bg-surface">
            <StatTile value={formatNumber(jobStats.total_jobs, locale)} label={t('totalJobs')} />
          </li>
          <li className="rounded-[var(--radius-md)] border border-border bg-surface">
            <StatTile
              value={
                jobStats.avg_completion_ms == null
                  ? '—'
                  : `${formatNumber(Math.round(jobStats.avg_completion_ms / 1000), locale)}s`
              }
              label={t('avgCompletion')}
              hint={jobStats.avg_completion_ms == null ? t('avgCompletionEmpty') : undefined}
            />
          </li>
        </ul>
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          <div className="rounded-[var(--radius-md)] border border-border bg-surface p-4">
            <p className="mb-2 text-xs font-semibold text-muted">{t('byStatus')}</p>
            <ul className="flex flex-col gap-1.5 text-sm">
              {Object.entries(jobStats.by_status ?? {}).map(([status, count]) => (
                <li key={status} className="flex items-center justify-between gap-4">
                  <span className="font-mono text-xs text-muted">{status}</span>
                  <span className="tabular font-medium">{formatNumber(count, locale)}</span>
                </li>
              ))}
            </ul>
          </div>
          <div className="rounded-[var(--radius-md)] border border-border bg-surface p-4">
            <p className="mb-2 text-xs font-semibold text-muted">{t('byOperation')}</p>
            <ul className="flex flex-col gap-1.5 text-sm">
              {Object.entries(jobStats.by_operation ?? {}).map(([operation, count]) => (
                <li key={operation} className="flex items-center justify-between gap-4">
                  <span className="font-mono text-xs text-muted">{operation}</span>
                  <span className="tabular font-medium">{formatNumber(count, locale)}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </section>
    </div>
  );
}
