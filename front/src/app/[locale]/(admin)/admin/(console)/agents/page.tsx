import { getLocale, getTranslations } from 'next-intl/server';

import { AgentRunsTable } from '@/components/admin/agents/agent-runs-table';
import { PageHeading, StatTile } from '@/components/ui/primitives';
import type { Locale } from '@/i18n/routing';
import { adminFetch } from '@/lib/api/admin-server';
import type { AgentUsage, Page } from '@/lib/api/admin-types';
import { formatNumber } from '@/lib/format';

export async function generateMetadata() {
  const t = await getTranslations('adminAgents');
  return { title: t('title') };
}

export default async function AdminAgentsPage() {
  const t = await getTranslations('adminAgents');
  const locale = (await getLocale()) as Locale;

  const usage = await adminFetch<Page<AgentUsage>>('/v1/admin/agent-runs/usage', {
    query: { hours: 24 },
  });

  return (
    <div className="flex flex-col gap-6">
      <PageHeading title={t('title')} description={t('subtitle')} />

      <section>
        <h2 className="mb-3 text-sm font-semibold">{t('usage')}</h2>
        <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {usage.items.map((row) => (
            <li
              key={row.agent_name}
              className="rounded-[var(--radius-md)] border border-border bg-surface"
            >
              <StatTile
                value={formatNumber(row.runs, locale)}
                label={row.agent_name}
                hint={`${t('colTokens')} ${formatNumber(row.total_tokens, locale)} · ${formatNumber(row.avg_latency_ms, locale)}ms`}
                // A non-zero fallback count is the number an operator is
                // looking for on this page, so it is coloured.
                tone={row.degraded_runs > 0 ? 'amber' : undefined}
              />
              {row.degraded_runs > 0 ? (
                <p className="px-5 pb-4 text-[11px] text-amber">
                  {t('degradedCount', { count: row.degraded_runs })}
                </p>
              ) : null}
            </li>
          ))}
        </ul>
      </section>

      <AgentRunsTable />
    </div>
  );
}
