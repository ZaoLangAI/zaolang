import { getLocale, getTranslations } from 'next-intl/server';

import { Badge, PageHeading, StatTile } from '@/components/ui/primitives';
import type { Locale } from '@/i18n/routing';
import { adminFetch } from '@/lib/api/admin-server';
import type {
  AgentUsage,
  JobStats,
  Page,
  ProviderStat,
  Reconciliation,
} from '@/lib/api/admin-types';
import { formatDateTime, formatNumber } from '@/lib/format';

export async function generateMetadata() {
  const t = await getTranslations('adminStatistics');
  return { title: t('title') };
}

const JOB_STATS_WINDOW_HOURS = 24;

export default async function AdminStatisticsPage() {
  const t = await getTranslations('adminStatistics');
  const tAgents = await getTranslations('adminAgents');
  const tCredits = await getTranslations('adminCredits');
  const locale = (await getLocale()) as Locale;

  const [providerStats, agentUsage, jobStats, reconciliation] = await Promise.all([
    adminFetch<Page<ProviderStat>>('/v1/admin/providers/stats'),
    adminFetch<Page<AgentUsage>>('/v1/admin/agent-runs/usage', {
      query: { hours: JOB_STATS_WINDOW_HOURS },
    }),
    adminFetch<JobStats>('/v1/admin/jobs/stats', { query: { hours: JOB_STATS_WINDOW_HOURS } }),
    adminFetch<Reconciliation>('/v1/admin/credits/reconciliation'),
  ]);

  return (
    <div className="flex flex-col gap-8">
      <PageHeading title={t('title')} description={t('subtitle')} />

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
              {providerStats.items.map((stat) => (
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
        <h2 className="mb-3 text-sm font-semibold">{t('sectionAgents')}</h2>
        <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {agentUsage.items.map((row) => (
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
    </div>
  );
}
