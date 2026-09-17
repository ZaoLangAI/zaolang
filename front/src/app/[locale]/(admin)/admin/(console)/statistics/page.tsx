import { getTranslations } from 'next-intl/server';

import { StatisticsWorkspace } from '@/components/admin/statistics/statistics-workspace';
import { PageHeading } from '@/components/ui/primitives';
import { adminFetchOrNull } from '@/lib/api/admin-server';
import type {
  AgentTimeseries,
  AgentUsage,
  ContentTimeseries,
  CostBreakdown,
  CostTimeseries,
  CreditFlowTimeseries,
  JobStats,
  JobsTimeseries,
  Page,
  ProviderStat,
  ProviderTimeseries,
  Reconciliation,
  SystemHealth,
  UserGrowthTimeseries,
} from '@/lib/api/admin-types';

export async function generateMetadata() {
  const t = await getTranslations('adminStatistics');
  return { title: t('title') };
}

const JOB_STATS_WINDOW_HOURS = 24;
const DEFAULT_TIMESERIES_DAYS = 30;

export default async function AdminStatisticsPage() {
  const t = await getTranslations('adminStatistics');

  const generatedAt = new Date().toISOString();
  const emptySeries = {
    generated_at: generatedAt,
    window_days: DEFAULT_TIMESERIES_DAYS,
    points: [],
  };

  const [
    providerStats,
    agentUsage,
    jobStats,
    reconciliation,
    health,
    jobsTimeseries,
    providersTimeseries,
    agentsTimeseries,
    costsTimeseries,
    costsBreakdown,
    creditsTimeseries,
    contentTimeseries,
    usersTimeseries,
  ] = await Promise.all([
    adminFetchOrNull<Page<ProviderStat>>('/v1/admin/providers/stats'),
    adminFetchOrNull<Page<AgentUsage>>('/v1/admin/agent-runs/usage', {
      query: { hours: JOB_STATS_WINDOW_HOURS },
    }),
    adminFetchOrNull<JobStats>('/v1/admin/jobs/stats', {
      query: { hours: JOB_STATS_WINDOW_HOURS },
    }),
    adminFetchOrNull<Reconciliation>('/v1/admin/credits/reconciliation'),
    adminFetchOrNull<SystemHealth>('/v1/admin/health'),
    adminFetchOrNull<JobsTimeseries>('/v1/admin/statistics/jobs', {
      query: { days: DEFAULT_TIMESERIES_DAYS },
    }),
    adminFetchOrNull<ProviderTimeseries>('/v1/admin/statistics/providers', {
      query: { days: DEFAULT_TIMESERIES_DAYS },
    }),
    adminFetchOrNull<AgentTimeseries>('/v1/admin/statistics/agents', {
      query: { days: DEFAULT_TIMESERIES_DAYS },
    }),
    adminFetchOrNull<CostTimeseries>('/v1/admin/statistics/costs', {
      query: { days: DEFAULT_TIMESERIES_DAYS },
    }),
    adminFetchOrNull<CostBreakdown>('/v1/admin/statistics/costs/breakdown', {
      query: { days: DEFAULT_TIMESERIES_DAYS },
    }),
    adminFetchOrNull<CreditFlowTimeseries>('/v1/admin/statistics/credits', {
      query: { days: DEFAULT_TIMESERIES_DAYS },
    }),
    adminFetchOrNull<ContentTimeseries>('/v1/admin/statistics/content', {
      query: { days: DEFAULT_TIMESERIES_DAYS },
    }),
    adminFetchOrNull<UserGrowthTimeseries>('/v1/admin/statistics/users', {
      query: { days: DEFAULT_TIMESERIES_DAYS },
    }),
  ]);

  return (
    <div className="flex flex-col gap-8">
      <PageHeading title={t('title')} description={t('subtitle')} />

      <StatisticsWorkspace
        initialRange={DEFAULT_TIMESERIES_DAYS}
        providerStats={providerStats?.items ?? []}
        agentUsage={agentUsage?.items ?? []}
        jobStats={
          jobStats ?? {
            generated_at: generatedAt,
            window_hours: JOB_STATS_WINDOW_HOURS,
            total_jobs: 0,
          }
        }
        reconciliation={
          reconciliation ?? {
            generated_at: generatedAt,
            account_count: 0,
            mismatched_account_count: 0,
            dangling_reserved_count: 0,
          }
        }
        health={
          health ?? {
            services: [],
            queues: [],
            llm_reachable: false,
            app_version: '',
            generated_at: generatedAt,
          }
        }
        initialSeries={{
          jobs: jobsTimeseries ?? emptySeries,
          providers: providersTimeseries ?? emptySeries,
          agents: agentsTimeseries ?? emptySeries,
          costs: costsTimeseries ?? { ...emptySeries, total_micro_usd: 0 },
          costBreakdown: costsBreakdown ?? {
            generated_at: generatedAt,
            window_days: DEFAULT_TIMESERIES_DAYS,
            providers: [],
            models: [],
          },
          credits: creditsTimeseries ?? emptySeries,
          content: contentTimeseries ?? emptySeries,
          users: usersTimeseries ?? { ...emptySeries, total_users: 0, suspended_users: 0 },
        }}
      />
    </div>
  );
}
