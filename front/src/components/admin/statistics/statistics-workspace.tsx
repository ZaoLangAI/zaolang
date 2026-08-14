'use client';

import { useTranslations } from 'next-intl';
import { useEffect, useState } from 'react';

import { ContentPanel } from '@/components/admin/statistics/content-panel';
import { CreditsPanel } from '@/components/admin/statistics/credits-panel';
import { JobsPanel } from '@/components/admin/statistics/jobs-panel';
import { OverviewPanel } from '@/components/admin/statistics/overview-panel';
import { ProvidersAgentsPanel } from '@/components/admin/statistics/providers-agents-panel';
import { SystemPanel } from '@/components/admin/statistics/system-panel';
import { UsersPanel } from '@/components/admin/statistics/users-panel';
import { cn } from '@/lib/cn';
import { adminApi } from '@/lib/api/admin-client';
import type {
  AgentTimeseries,
  AgentUsage,
  ContentTimeseries,
  CreditFlowTimeseries,
  JobStats,
  JobsTimeseries,
  ProviderStat,
  ProviderTimeseries,
  Reconciliation,
  StorageUsage,
  SystemHealth,
  UserGrowthTimeseries,
} from '@/lib/api/admin-types';

const TABS = [
  'overview',
  'jobs',
  'providers',
  'credits',
  'content',
  'users',
  'system',
] as const;
type Tab = (typeof TABS)[number];

const RANGES = [7, 30, 90] as const;
type Range = (typeof RANGES)[number];

interface Timeseries {
  jobs: JobsTimeseries;
  providers: ProviderTimeseries;
  agents: AgentTimeseries;
  credits: CreditFlowTimeseries;
  content: ContentTimeseries;
  users: UserGrowthTimeseries;
}

/**
 * The statistics module's shell: one route, seven scenario tabs.
 *
 * Every tab's data is fetched once on the server and handed down here (like
 * `library-tabs.tsx` does for the collection page) so switching tabs never
 * re-fetches or shows a spinner. Only changing the day range re-fetches —
 * and it re-fetches every series at once rather than per-tab, since the
 * payloads are small and it keeps the range control global and predictable.
 */
export function StatisticsWorkspace({
  initialRange,
  providerStats,
  agentUsage,
  jobStats,
  reconciliation,
  health,
  storageUsage,
  initialSeries,
}: {
  initialRange: Range;
  providerStats: ProviderStat[];
  agentUsage: AgentUsage[];
  jobStats: JobStats;
  reconciliation: Reconciliation;
  health: SystemHealth;
  storageUsage: StorageUsage;
  initialSeries: Timeseries;
}) {
  const t = useTranslations('adminStatistics');
  const [tab, setTab] = useState<Tab>('overview');
  const [range, setRange] = useState<Range>(initialRange);
  // Tagged with the range it answers, so "loading" and "which series to show"
  // are both derived from comparing `range` to `fetched.range` instead of
  // being tracked as separate state an effect has to keep in sync.
  const [fetched, setFetched] = useState<{ range: Range; series: Timeseries } | null>(null);

  useEffect(() => {
    if (range === initialRange) return;
    let cancelled = false;
    const query = { days: range };
    Promise.all([
      adminApi.get<JobsTimeseries>('/v1/admin/statistics/jobs', { query }),
      adminApi.get<ProviderTimeseries>('/v1/admin/statistics/providers', { query }),
      adminApi.get<AgentTimeseries>('/v1/admin/statistics/agents', { query }),
      adminApi.get<CreditFlowTimeseries>('/v1/admin/statistics/credits', { query }),
      adminApi.get<ContentTimeseries>('/v1/admin/statistics/content', { query }),
      adminApi.get<UserGrowthTimeseries>('/v1/admin/statistics/users', { query }),
    ]).then(([jobs, providers, agents, credits, content, users]) => {
      if (cancelled) return;
      setFetched({ range, series: { jobs, providers, agents, credits, content, users } });
    });
    return () => {
      cancelled = true;
    };
  }, [range, initialRange]);

  const series = range === initialRange || fetched?.range !== range ? initialSeries : fetched.series;
  const loading = range !== initialRange && fetched?.range !== range;

  const labels: Record<Tab, string> = {
    overview: t('tabOverview'),
    jobs: t('tabJobs'),
    providers: t('tabProviders'),
    credits: t('tabCredits'),
    content: t('tabContent'),
    users: t('tabUsers'),
    system: t('tabSystem'),
  };

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border">
        <div role="tablist" aria-label={t('title')} className="flex flex-wrap gap-6">
          {TABS.map((id) => (
            <button
              key={id}
              role="tab"
              type="button"
              aria-selected={tab === id}
              onClick={() => setTab(id)}
              className={cn(
                '-mb-px border-b-2 pb-3 text-sm transition-colors',
                tab === id
                  ? 'border-primary text-text'
                  : 'border-transparent text-muted hover:text-text',
              )}
            >
              {labels[id]}
            </button>
          ))}
        </div>

        {tab !== 'overview' && tab !== 'system' ? (
          <div className="mb-2 flex items-center gap-2">
            <span className="text-xs text-muted">{t('rangeLabel')}</span>
            <div className="flex gap-1 rounded-full border border-border bg-surface-soft p-0.5">
              {RANGES.map((option) => (
                <button
                  key={option}
                  type="button"
                  onClick={() => setRange(option)}
                  className={cn(
                    'rounded-full px-3 py-1 text-xs transition-colors',
                    range === option
                      ? 'bg-primary text-on-primary'
                      : 'text-muted hover:text-text',
                  )}
                >
                  {t(`range${option}d` as 'range7d' | 'range30d' | 'range90d')}
                </button>
              ))}
            </div>
            {loading ? <span className="text-xs text-muted">{t('refreshing')}</span> : null}
          </div>
        ) : null}
      </div>

      {tab === 'overview' ? (
        <OverviewPanel
          jobsToday={series.jobs.points?.at(-1)}
          usersToday={series.users.points?.at(-1)}
          agentsToday={series.agents.points?.at(-1)}
          reconciliation={reconciliation}
          health={health}
        />
      ) : null}
      {tab === 'jobs' ? <JobsPanel jobStats={jobStats} timeseries={series.jobs} /> : null}
      {tab === 'providers' ? (
        <ProvidersAgentsPanel
          providerStats={providerStats}
          agentUsage={agentUsage}
          providerSeries={series.providers}
          agentSeries={series.agents}
        />
      ) : null}
      {tab === 'credits' ? (
        <CreditsPanel reconciliation={reconciliation} timeseries={series.credits} />
      ) : null}
      {tab === 'content' ? <ContentPanel timeseries={series.content} /> : null}
      {tab === 'users' ? <UsersPanel timeseries={series.users} /> : null}
      {tab === 'system' ? <SystemPanel health={health} storageUsage={storageUsage} /> : null}
    </div>
  );
}
