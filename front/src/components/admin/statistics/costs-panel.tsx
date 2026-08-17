'use client';

import { useLocale, useTranslations } from 'next-intl';

import { TrendChart, type TrendColor } from '@/components/admin/statistics/trend-chart';
import { EmptyState, StatTile } from '@/components/ui/primitives';
import type { Locale } from '@/i18n/routing';
import { formatMicroUsd } from '@/lib/admin/micro-usd';
import type { CostBreakdown, CostTimeseries } from '@/lib/api/admin-types';
import { formatNumber } from '@/lib/format';

/** Recharts is given one line per vendor, and five is where a line chart
 * stops being readable. The rest of the vendors are still in the table
 * below, so nothing is hidden — only un-plotted. */
const MAX_PLOTTED_PROVIDERS = 5;
const PROVIDER_COLORS = [
  'primary',
  'success',
  'amber',
  'danger',
  'muted',
] as const satisfies readonly TrendColor[];

type ProviderCostSeries = NonNullable<CostBreakdown['providers']>[number];

export function CostsPanel({
  timeseries,
  breakdown,
}: {
  timeseries: CostTimeseries;
  breakdown: CostBreakdown;
}) {
  const t = useTranslations('adminStatistics');
  const locale = useLocale() as Locale;

  const points = timeseries.points ?? [];
  const providers = (breakdown.providers ?? [])
    .slice()
    .sort((a, b) => b.total_micro_usd - a.total_micro_usd);
  const models = (breakdown.models ?? [])
    .slice()
    .sort((a, b) => b.total_micro_usd - a.total_micro_usd);

  const llmTotal = points.reduce((sum, point) => sum + point.llm_micro_usd, 0);
  const mediaTotal = points.reduce((sum, point) => sum + point.media_micro_usd, 0);

  const plotted = providers.slice(0, MAX_PLOTTED_PROVIDERS);
  const cumulativeByProvider = buildCumulativeSeries(plotted);

  return (
    <div className="flex flex-col gap-6">
      <section>
        <h2 className="mb-3 text-sm font-semibold">{t('sectionCosts')}</h2>
        <ul className="grid gap-3 sm:grid-cols-3">
          <li className="rounded-[var(--radius-md)] border border-border bg-surface">
            <StatTile
              value={formatMicroUsd(timeseries.total_micro_usd)}
              label={t('costTotal')}
              hint={t('costTotalHint', { days: timeseries.window_days })}
            />
          </li>
          <li className="rounded-[var(--radius-md)] border border-border bg-surface">
            <StatTile value={formatMicroUsd(llmTotal)} label={t('costLlm')} />
          </li>
          <li className="rounded-[var(--radius-md)] border border-border bg-surface">
            <StatTile value={formatMicroUsd(mediaTotal)} label={t('costMedia')} />
          </li>
        </ul>
      </section>

      <section>
        <h2 className="mb-3 text-sm font-semibold">{t('costDailyChartTitle')}</h2>
        <div className="rounded-[var(--radius-md)] border border-border bg-surface p-4">
          <TrendChart
            data={points}
            emptyTitle={t('chartEmpty')}
            valueFormatter={(value) => formatMicroUsd(value)}
            series={[
              { dataKey: 'total_micro_usd', label: t('costTotal'), color: 'primary' },
              { dataKey: 'llm_micro_usd', label: t('costLlm'), color: 'success' },
              { dataKey: 'media_micro_usd', label: t('costMedia'), color: 'amber' },
            ]}
          />
        </div>
      </section>

      <section>
        <h2 className="mb-1 text-sm font-semibold">{t('costProviderChartTitle')}</h2>
        <p className="mb-3 text-xs text-muted">{t('costProviderChartHint')}</p>
        <div className="rounded-[var(--radius-md)] border border-border bg-surface p-4">
          <TrendChart
            data={cumulativeByProvider}
            emptyTitle={t('chartEmpty')}
            valueFormatter={(value) => formatMicroUsd(value)}
            series={plotted.map((provider, index) => ({
              dataKey: provider.endpoint_id,
              label: provider.endpoint_name || provider.endpoint_id,
              color: PROVIDER_COLORS[index % PROVIDER_COLORS.length] ?? 'muted',
            }))}
          />
        </div>
      </section>

      <section>
        <h2 className="mb-1 text-sm font-semibold">{t('costModelTableTitle')}</h2>
        <p className="mb-3 text-xs text-muted">{t('costModelTableHint')}</p>
        {models.length === 0 ? (
          <EmptyState title={t('chartEmpty')} />
        ) : (
          <div className="overflow-x-auto rounded-[var(--radius-md)] border border-border">
            <table className="w-full text-left text-sm">
              <caption className="sr-only">{t('costModelTableTitle')}</caption>
              <thead className="bg-surface-soft text-xs text-muted">
                <tr>
                  <th scope="col" className="px-3 py-2.5 font-medium">
                    {t('costColModel')}
                  </th>
                  <th scope="col" className="px-3 py-2.5 font-medium">
                    {t('costColProvider')}
                  </th>
                  <th scope="col" className="px-3 py-2.5 text-right font-medium">
                    {t('costColCalls')}
                  </th>
                  <th scope="col" className="px-3 py-2.5 text-right font-medium">
                    {t('costColTotal')}
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border bg-surface">
                {models.map((model) => (
                  <tr key={`${model.endpoint_id}-${model.model}-${model.kind}`}>
                    <th scope="row" className="px-3 py-2.5 text-left font-normal">
                      <span className="font-mono text-xs">
                        {model.model || t('costModelUnknown')}
                      </span>
                      <span className="ml-2 text-[11px] text-muted">
                        {model.kind === 'media' ? t('costKindMedia') : t('costKindLlm')}
                      </span>
                    </th>
                    <td className="px-3 py-2.5 text-xs text-muted">
                      {model.endpoint_name || model.endpoint_id}
                    </td>
                    <td className="tabular px-3 py-2.5 text-right text-xs">
                      {formatNumber(model.calls, locale)}
                    </td>
                    <td className="tabular px-3 py-2.5 text-right text-xs">
                      {formatMicroUsd(model.total_micro_usd)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}

/**
 * Turns per-provider daily points into one row per date, carrying a running
 * total per provider.
 *
 * Cumulative rather than daily because the question this chart answers is
 * "which vendor is the money going to", and a daily line answers it badly:
 * spend is bursty, so the ordering flips day to day even when one vendor is
 * clearly dominant over the window. A provider with no spend on a given day
 * still holds its previous total, so its line runs flat rather than falling
 * to zero.
 */
function buildCumulativeSeries(
  providers: ProviderCostSeries[],
): Array<{ date: string } & Record<string, number | string>> {
  const dates = new Set<string>();
  for (const provider of providers) {
    for (const point of provider.points ?? []) dates.add(point.date);
  }

  const running = new Map<string, number>();
  return Array.from(dates)
    .sort()
    .map((date) => {
      const row: { date: string } & Record<string, number | string> = { date };
      for (const provider of providers) {
        const today = (provider.points ?? []).find((point) => point.date === date);
        const total = (running.get(provider.endpoint_id) ?? 0) + (today?.total_micro_usd ?? 0);
        running.set(provider.endpoint_id, total);
        row[provider.endpoint_id] = total;
      }
      return row;
    });
}
