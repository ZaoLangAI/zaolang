'use client';

import { useLocale, useTranslations } from 'next-intl';

import { StatTile } from '@/components/ui/primitives';
import type { Locale } from '@/i18n/routing';
import type {
  AgentDailyPoint,
  JobsDailyPoint,
  Reconciliation,
  SystemHealth,
  UserGrowthDailyPoint,
} from '@/lib/api/admin-types';
import { formatNumber } from '@/lib/format';

/**
 * Cross-domain KPI cards assembled from data every other tab already has —
 * no dedicated endpoint, per the plan's "reuse, don't invent" constraint.
 */
export function OverviewPanel({
  jobsToday,
  usersToday,
  agentsToday,
  reconciliation,
  health,
}: {
  jobsToday?: JobsDailyPoint;
  usersToday?: UserGrowthDailyPoint;
  agentsToday?: AgentDailyPoint;
  reconciliation: Reconciliation;
  health: SystemHealth;
}) {
  const t = useTranslations('adminStatistics');
  const locale = useLocale() as Locale;

  const jobsTotal = jobsToday?.total ?? 0;
  const successRate =
    jobsTotal > 0 ? `${(((jobsToday?.succeeded ?? 0) / jobsTotal) * 100).toFixed(1)}%` : '—';
  const queueBacklog = health.queues.reduce((sum, queue) => sum + Math.max(queue.depth, 0), 0);

  return (
    <div className="flex flex-col gap-6">
      <p className="text-sm text-muted">{t('overviewSubtitle')}</p>
      <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <li className="rounded-[var(--radius-md)] border border-border bg-surface">
          <StatTile value={formatNumber(jobsTotal, locale)} label={t('kpiJobsToday')} />
        </li>
        <li className="rounded-[var(--radius-md)] border border-border bg-surface">
          <StatTile value={successRate} label={t('kpiJobSuccessRate')} />
        </li>
        <li className="rounded-[var(--radius-md)] border border-border bg-surface">
          <StatTile
            value={formatNumber(usersToday?.new_users ?? 0, locale)}
            label={t('kpiNewUsersToday')}
          />
        </li>
        <li className="rounded-[var(--radius-md)] border border-border bg-surface">
          <StatTile
            value={formatNumber(reconciliation.mismatched_account_count, locale)}
            label={t('kpiReconciliationIssues')}
            tone={reconciliation.mismatched_account_count > 0 ? 'danger' : 'success'}
          />
        </li>
        <li className="rounded-[var(--radius-md)] border border-border bg-surface">
          <StatTile
            value={formatNumber(queueBacklog, locale)}
            label={t('kpiQueueBacklog')}
            tone={queueBacklog > 50 ? 'amber' : undefined}
          />
        </li>
        <li className="rounded-[var(--radius-md)] border border-border bg-surface">
          <StatTile
            value={formatNumber(agentsToday?.degraded_runs ?? 0, locale)}
            label={t('kpiAgentDegradedToday')}
            tone={(agentsToday?.degraded_runs ?? 0) > 0 ? 'amber' : undefined}
          />
        </li>
      </ul>
    </div>
  );
}
