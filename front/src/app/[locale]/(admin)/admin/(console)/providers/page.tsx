import { getLocale, getTranslations } from 'next-intl/server';

import { RoutingWeightsPanel } from '@/components/admin/providers/routing-weights-panel';
import { Badge, PageHeading } from '@/components/ui/primitives';
import type { Locale } from '@/i18n/routing';
import { adminFetch, adminFetchOrNull } from '@/lib/api/admin-server';
import type { ConfigValue, Page, ProviderStat } from '@/lib/api/admin-types';
import { formatNumber } from '@/lib/format';

export async function generateMetadata() {
  const t = await getTranslations('adminProviders');
  return { title: t('title') };
}

export default async function AdminProvidersPage() {
  const t = await getTranslations('adminProviders');
  const locale = (await getLocale()) as Locale;

  const [stats, routing] = await Promise.all([
    adminFetch<Page<ProviderStat>>('/v1/admin/providers/stats'),
    // Weights are operator-only, so a reviewer sees the statistics without the
    // editor rather than an error page.
    adminFetchOrNull<ConfigValue>('/v1/admin/config/routing_weights'),
  ]);

  return (
    <div className="flex flex-col gap-6">
      <PageHeading title={t('title')} description={t('subtitle')} />

      <div className="overflow-x-auto rounded-[var(--radius-md)] border border-border">
        <table className="w-full text-left text-sm">
          <caption className="sr-only">{t('title')}</caption>
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
            {stats.items.map((stat) => (
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

      {routing ? <RoutingWeightsPanel initial={routing} /> : null}
    </div>
  );
}
