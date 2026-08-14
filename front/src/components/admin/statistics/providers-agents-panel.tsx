'use client';

import { useLocale, useTranslations } from 'next-intl';

import { TrendChart } from '@/components/admin/statistics/trend-chart';
import { Badge, StatTile } from '@/components/ui/primitives';
import type { Locale } from '@/i18n/routing';
import type {
  AgentTimeseries,
  AgentUsage,
  ProviderStat,
  ProviderTimeseries,
} from '@/lib/api/admin-types';
import { formatNumber } from '@/lib/format';

export function ProvidersAgentsPanel({
  providerStats,
  agentUsage,
  providerSeries,
  agentSeries,
}: {
  providerStats: ProviderStat[];
  agentUsage: AgentUsage[];
  providerSeries: ProviderTimeseries;
  agentSeries: AgentTimeseries;
}) {
  const t = useTranslations('adminStatistics');
  const tAgents = useTranslations('adminAgents');
  const locale = useLocale() as Locale;

  return (
    <div className="flex flex-col gap-6">
      <section>
        <h2 className="mb-3 text-sm font-semibold">{t('providersChartTitle')}</h2>
        <div className="rounded-[var(--radius-md)] border border-border bg-surface p-4">
          <TrendChart
            data={providerSeries.points ?? []}
            emptyTitle={t('chartEmpty')}
            series={[
              { dataKey: 'attempts', label: t('providersChartAttempts'), color: 'muted' },
              { dataKey: 'successes', label: t('providersChartSuccesses'), color: 'success' },
            ]}
          />
        </div>
      </section>

      <section>
        <h2 className="mb-3 text-sm font-semibold">{t('sectionProviders')}</h2>
        <div className="overflow-x-auto rounded-[var(--radius-md)] border border-border">
          <table className="w-full text-left text-sm">
            <caption className="sr-only">{t('sectionProviders')}</caption>
            <thead className="bg-surface-soft text-xs text-muted">
              <tr>
                <th scope="col" className="px-3 py-2.5 font-medium">
                  {t('colProvider')}
                </th>
                <th scope="col" className="px-3 py-2.5 text-right font-medium">
                  {t('colAttempts')}
                </th>
                <th scope="col" className="px-3 py-2.5 text-right font-medium">
                  {t('colSuccess')}
                </th>
                <th scope="col" className="px-3 py-2.5 text-right font-medium">
                  {t('colLatency')}
                </th>
                <th scope="col" className="px-3 py-2.5 text-right font-medium">
                  {t('colCost')}
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border bg-surface">
              {providerStats.map((stat) => (
                <tr key={`${stat.provider}-${stat.operation}-${stat.quality_tier}`}>
                  <th scope="row" className="px-3 py-2.5 text-left font-normal">
                    <span className="font-mono text-xs">{stat.provider}</span>
                    <span className="ml-2 text-[11px] text-muted">
                      {stat.operation} · {stat.quality_tier}
                    </span>
                    <Badge tone={stat.enabled ? 'success' : 'neutral'} className="ml-2">
                      {stat.enabled ? t('enabled') : t('disabled')}
                    </Badge>
                  </th>
                  <td className="tabular px-3 py-2.5 text-right text-xs">
                    {formatNumber(stat.attempts, locale)}
                  </td>
                  <td className="tabular px-3 py-2.5 text-right text-xs">
                    {(stat.success_rate * 100).toFixed(1)}%
                  </td>
                  <td className="tabular px-3 py-2.5 text-right text-xs text-muted">
                    {formatNumber(stat.p50_latency_ms, locale)}ms
                  </td>
                  <td className="tabular px-3 py-2.5 text-right text-xs text-muted">
                    {formatNumber(stat.effective_cost, locale)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section>
        <h2 className="mb-3 text-sm font-semibold">{t('agentsChartTitle')}</h2>
        <div className="rounded-[var(--radius-md)] border border-border bg-surface p-4">
          <TrendChart
            data={agentSeries.points ?? []}
            emptyTitle={t('chartEmpty')}
            series={[
              { dataKey: 'runs', label: t('agentsChartRuns'), color: 'muted' },
              { dataKey: 'degraded_runs', label: t('agentsChartDegraded'), color: 'amber' },
            ]}
          />
        </div>
      </section>

      <section>
        <h2 className="mb-3 text-sm font-semibold">{t('sectionAgents')}</h2>
        <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {agentUsage.map((row) => (
            <li
              key={row.agent_name}
              className="rounded-[var(--radius-md)] border border-border bg-surface"
            >
              <StatTile
                value={formatNumber(row.runs, locale)}
                label={row.agent_name}
                hint={`${tAgents('colTokens')} ${formatNumber(row.total_tokens, locale)} · ${formatNumber(row.avg_latency_ms, locale)}ms`}
                tone={row.degraded_runs > 0 ? 'amber' : undefined}
              />
              {row.degraded_runs > 0 ? (
                <p className="px-5 pb-4 text-[11px] text-amber">
                  {tAgents('degradedCount', { count: row.degraded_runs })}
                </p>
              ) : null}
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
