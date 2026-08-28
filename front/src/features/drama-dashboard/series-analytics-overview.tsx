'use client';

import { useLocale, useTranslations } from 'next-intl';

import { BarComparisonChart } from '@/components/charts/bar-comparison-chart';
import { Button } from '@/components/ui/button';
import { IconRefresh } from '@/components/ui/icons';
import { ErrorNotice, SectionHeading, StatTile } from '@/components/ui/primitives';
import { Link } from '@/i18n/navigation';
import type { Locale } from '@/i18n/routing';
import { formatNumber } from '@/lib/format';
import { useResource } from '@/lib/use-resource';

import { ChannelMetricChartSkeleton } from './channel-metric-chart';
import { CHANNEL_LABEL_KEYS, SERIES_CHANNELS } from './channels';
import type * as distributionApi from './distribution-api';

/** Overview only needs a short recent window for its growth badge — the
 *  detail page fetches the full range the user picks there. */
const OVERVIEW_DAYS = 7;

/**
 * Compact per-platform totals sitting above the episode list on
 * `/create/short/series/{id}` — aggregated across every episode's final
 * cut (`GET /v1/drama-series/{id}/metrics`). The whole card is a link into
 * `.../analytics`, the per-episode × per-channel breakdown page. Always
 * renders the full KPI+chart layout, even with zero data.
 */
export function SeriesAnalyticsOverview({ seriesId }: { seriesId: string }) {
  const t = useTranslations('editor');
  const tActions = useTranslations('actions');
  const locale = useLocale() as Locale;
  const resource = useResource<distributionApi.SeriesMetricsSummary>(
    `/v1/drama-series/${seriesId}/metrics?days=${OVERVIEW_DAYS}`,
  );

  if (resource.status === 'idle' || resource.status === 'loading') {
    return (
      <section>
        <SectionHeading title={t('seriesAnalyticsOverviewTitle')} />
        <div className="rounded-[var(--radius-md)] border border-border bg-surface p-4">
          <ChannelMetricChartSkeleton channelCount={SERIES_CHANNELS.length} />
        </div>
      </section>
    );
  }

  if (resource.status === 'failed') {
    return (
      <section>
        <SectionHeading title={t('seriesAnalyticsOverviewTitle')} />
        <div className="rounded-[var(--radius-md)] border border-border bg-surface p-4">
          <ErrorNotice
            title={t('analyticsLoadFailed')}
            action={
              <Button
                size="sm"
                variant="secondary"
                icon={<IconRefresh className="size-3.5" />}
                onClick={resource.refetch}
              >
                {tActions('retry')}
              </Button>
            }
          />
        </div>
      </section>
    );
  }

  const totals = resource.data?.totals ?? [];
  const coverage = resource.data?.coverage;
  const periodComparison = resource.data?.period_comparison ?? [];

  const totalViews = totals.reduce((sum, item) => sum + item.view_count, 0);
  const totalLikes = totals.reduce((sum, item) => sum + item.like_count, 0);
  const totalComments = totals.reduce((sum, item) => sum + item.comment_count, 0);
  const totalShares = totals.reduce((sum, item) => sum + item.share_count, 0);
  const engagementRate =
    totalViews > 0 ? (totalLikes + totalComments + totalShares) / totalViews : 0;

  // Combining a per-channel growth % across channels has no single correct
  // answer without the raw deltas the API doesn't expose here — showing the
  // busiest channel's own figure is the honest reading, not an average.
  const leadChannel = [...totals].sort((a, b) => b.view_count - a.view_count)[0];
  const leadGrowthPct = leadChannel
    ? (periodComparison.find((item) => item.channel === leadChannel.channel)
        ?.view_count_change_pct ?? null)
    : null;

  return (
    <section>
      <SectionHeading
        title={t('seriesAnalyticsOverviewTitle')}
        description={totals.length === 0 ? t('seriesAnalyticsOverviewEmpty') : undefined}
      />
      <Link
        href={`/create/short/series/${seriesId}/analytics`}
        className="block rounded-[var(--radius-md)] border border-border bg-surface p-4 transition-colors hover:border-border-strong hover:bg-surface-soft"
      >
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <StatTile
            value={formatNumber(totalViews, locale)}
            label={t('analyticsViews')}
            hint={
              leadGrowthPct !== null
                ? t('analyticsPeriodChangeHint', { pct: Math.round(leadGrowthPct * 100) })
                : undefined
            }
            tone={leadGrowthPct !== null && leadGrowthPct < 0 ? 'danger' : undefined}
          />
          <StatTile value={formatNumber(totalLikes, locale)} label={t('analyticsLikes')} />
          <StatTile
            value={`${Math.round(engagementRate * 1000) / 10}%`}
            label={t('analyticsEngagementRate')}
          />
          {coverage ? (
            <StatTile
              value={`${coverage.episodes_with_final_cut}/${coverage.total_episodes}`}
              label={t('coverageFinalCutLabel')}
              hint={t('coverageDistributedHint', {
                distributed: coverage.episodes_distributed,
                channels: coverage.channels_covered.length,
              })}
            />
          ) : null}
        </div>
        <div className="mt-4">
          <BarComparisonChart
            height={160}
            emptyTitle={t('seriesAnalyticsOverviewEmpty')}
            data={SERIES_CHANNELS.map((channel) => ({
              label: t(CHANNEL_LABEL_KEYS[channel] ?? channel),
              view_count: totals.find((item) => item.channel === channel)?.view_count ?? 0,
            }))}
            series={[{ dataKey: 'view_count', label: t('analyticsViews'), color: 'primary' }]}
          />
        </div>
        <p className="mt-3 text-xs text-primary">{t('seriesAnalyticsViewDetail')}</p>
      </Link>
    </section>
  );
}
