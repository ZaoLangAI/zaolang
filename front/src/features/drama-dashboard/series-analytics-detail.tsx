'use client';

import { useLocale, useTranslations } from 'next-intl';
import { useCallback, useEffect, useState } from 'react';

import { BarComparisonChart } from '@/components/charts/bar-comparison-chart';
import { ChannelSharePieChart } from '@/components/charts/channel-share-pie-chart';
import { TrendChart, type TrendColor, type TrendSeriesDef } from '@/components/charts/trend-chart';
import { useSession } from '@/components/auth/session-provider';
import { SignInPrompt } from '@/components/auth/sign-in-prompt';
import { Button } from '@/components/ui/button';
import { IconRefresh } from '@/components/ui/icons';
import { EmptyState, ErrorNotice, SectionHeading, StatTile } from '@/components/ui/primitives';
import { Spinner } from '@/components/ui/spinner';
import type { Locale } from '@/i18n/routing';
import { isApiError } from '@/lib/api/errors';
import { cn } from '@/lib/cn';
import { formatNumber } from '@/lib/format';

import { ChannelMetricChart } from './channel-metric-chart';
import { CHANNEL_LABEL_KEYS, SERIES_CHANNELS } from './channels';
import * as distributionApi from './distribution-api';
import { downloadCsv } from './export-csv';
import { rankEpisodesByViews } from './episode-ranking';

const RANGES = [7, 30, 90] as const;
type Range = (typeof RANGES)[number];

const SERIES_COLORS: TrendColor[] = ['primary', 'success', 'amber', 'danger', 'muted'];

type PivotRow = { date: string } & Record<string, number | string>;

function pivotByChannel<T extends { date: string; channel: string }>(
  points: T[],
  valueKey: keyof T,
  prefix: string,
): { rows: PivotRow[]; channels: string[] } {
  const byDate = new Map<string, PivotRow>();
  const channels = new Set<string>();
  for (const point of points) {
    channels.add(point.channel);
    const row = byDate.get(point.date) ?? ({ date: point.date } as PivotRow);
    row[`${prefix}_${point.channel}`] = Number(point[valueKey]);
    byDate.set(point.date, row);
  }
  const rows = Array.from(byDate.values()).sort((a, b) => a.date.localeCompare(b.date));
  return { rows, channels: Array.from(channels).sort() };
}

/**
 * `/create/short/series/{seriesId}/analytics`: the detail page behind the
 * overview card on the series page — same `GET .../metrics` response, now
 * carrying trend/comparison/coverage data alongside the per-episode table.
 */
export function SeriesAnalyticsDetail({ seriesId }: { seriesId: string }) {
  const t = useTranslations('editor');
  const tActions = useTranslations('actions');
  const locale = useLocale() as Locale;
  const { status } = useSession();

  const [days, setDays] = useState<Range>(30);
  const [summary, setSummary] = useState<distributionApi.SeriesMetricsSummary | null>(null);
  // The range this `summary` actually answers — comparing it to `days`
  // derives "a range change is refreshing" instead of a separate boolean
  // state flipped synchronously inside the effect below (that pattern trips
  // the "no setState synchronously in an effect body" rule; every setState
  // call here happens inside a `.then`/`.catch`, after the effect itself
  // has finished running).
  const [loadedDays, setLoadedDays] = useState<Range | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [notFound, setNotFound] = useState(false);
  const [loadError, setLoadError] = useState(false);

  const load = useCallback(() => {
    if (status !== 'authenticated') return;
    void distributionApi
      .getSeriesMetrics(seriesId, days)
      .then((result) => {
        setSummary(result);
        setNotFound(false);
        setLoadError(false);
        setLoaded(true);
        setLoadedDays(days);
      })
      .catch((error: unknown) => {
        // A retry's outcome always fully replaces the previous one's flags —
        // never leave a stale `notFound`/`loadError` from an earlier attempt
        // set alongside this attempt's own result.
        if (isApiError(error) && error.isNotFound) {
          setNotFound(true);
          setLoadError(false);
        } else {
          setLoadError(true);
          setNotFound(false);
        }
        setLoaded(true);
        setLoadedDays(days);
      });
  }, [seriesId, status, days]);

  useEffect(() => {
    load();
  }, [load]);

  const refreshing = loaded && loadedDays !== null && loadedDays !== days;

  if (status === 'anonymous') return <SignInPrompt description={t('signInHint')} />;
  if (status === 'loading' || !loaded) {
    return (
      <div className="grid min-h-[40vh] place-items-center">
        <Spinner label={t('dashboardLoading')} />
      </div>
    );
  }
  if (notFound || (!summary && !loadError)) {
    return (
      <EmptyState title={t('dashboardUnavailable')} description={t('dashboardUnavailableHint')} />
    );
  }
  if (loadError && !summary) {
    return (
      <ErrorNotice
        title={t('analyticsLoadFailed')}
        action={
          <Button
            size="sm"
            variant="secondary"
            icon={<IconRefresh className="size-3.5" />}
            onClick={load}
          >
            {tActions('retry')}
          </Button>
        }
      />
    );
  }
  if (!summary) return null;

  const totals = summary.totals;
  const totalViews = totals.reduce((sum, item) => sum + item.view_count, 0);
  const totalLikes = totals.reduce((sum, item) => sum + item.like_count, 0);
  const totalComments = totals.reduce((sum, item) => sum + item.comment_count, 0);
  const totalShares = totals.reduce((sum, item) => sum + item.share_count, 0);
  const engagementRate =
    totalViews > 0 ? (totalLikes + totalComments + totalShares) / totalViews : 0;
  const finishRates = summary.episodes
    .map((row) => row.finish_rate)
    .filter((rate): rate is number => rate !== null);
  const avgFinishRate =
    finishRates.length > 0
      ? finishRates.reduce((sum, rate) => sum + rate, 0) / finishRates.length
      : null;
  const latestFollowerTotal = SERIES_CHANNELS.reduce((sum, channel) => {
    const points = summary.followers.filter((point) => point.channel === channel);
    const latest = points.at(-1);
    return sum + (latest ? latest.follower_count : 0);
  }, 0);
  const hasFollowerData = summary.followers.length > 0;

  const leadChannel = [...totals].sort((a, b) => b.view_count - a.view_count)[0];
  const leadComparison = leadChannel
    ? summary.period_comparison.find((item) => item.channel === leadChannel.channel)
    : undefined;

  const viewsDaily = pivotByChannel(summary.daily, 'view_count', 'view');
  const followersDaily = pivotByChannel(summary.followers, 'follower_count', 'follower');

  const viewsSeries: TrendSeriesDef[] = viewsDaily.channels.map((channel, index) => ({
    dataKey: `view_${channel}`,
    label: t(CHANNEL_LABEL_KEYS[channel] ?? channel),
    color: SERIES_COLORS[index % SERIES_COLORS.length]!,
  }));
  const followersSeries: TrendSeriesDef[] = followersDaily.channels.map((channel, index) => ({
    dataKey: `follower_${channel}`,
    label: t(CHANNEL_LABEL_KEYS[channel] ?? channel),
    color: SERIES_COLORS[index % SERIES_COLORS.length]!,
  }));

  const ranking = rankEpisodesByViews(summary.episodes).slice(0, 5);

  const exportEpisodesCsv = () => {
    downloadCsv(
      `series-${seriesId}-analytics.csv`,
      [
        'episode_number',
        'episode_title',
        'channel',
        'view_count',
        'like_count',
        'comment_count',
        'share_count',
        'finish_rate',
        'avg_play_duration_ms',
      ],
      summary.episodes.map((row) => [
        row.episode_number,
        row.episode_title,
        t(CHANNEL_LABEL_KEYS[row.channel] ?? row.channel),
        row.view_count,
        row.like_count,
        row.comment_count,
        row.share_count,
        row.finish_rate !== null ? Math.round(row.finish_rate * 10000) / 100 : '',
        row.avg_play_duration_ms ?? '',
      ]),
    );
  };

  return (
    <div className="flex flex-col gap-8">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <SectionHeading
          title={t('seriesAnalyticsDetailTitle')}
          description={summary.totals.length === 0 ? t('seriesAnalyticsOverviewEmpty') : undefined}
        />
        <div className="mb-2 flex items-center gap-2">
          <span className="text-xs text-muted">{t('analyticsRangeLabel')}</span>
          <div className="flex gap-1 rounded-full border border-border bg-surface-soft p-0.5">
            {RANGES.map((option) => (
              <button
                key={option}
                type="button"
                onClick={() => setDays(option)}
                className={cn(
                  'rounded-full px-3 py-1 text-xs transition-colors',
                  days === option ? 'bg-primary text-on-primary' : 'text-muted hover:text-text',
                )}
              >
                {t(
                  `analyticsRange${option}d` as
                    'analyticsRange7d' | 'analyticsRange30d' | 'analyticsRange90d',
                )}
              </button>
            ))}
          </div>
          {refreshing ? (
            <span className="text-xs text-muted">{t('analyticsRefreshing')}</span>
          ) : null}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 rounded-[var(--radius-md)] border border-border bg-surface p-4 sm:grid-cols-3 lg:grid-cols-6">
        <StatTile
          value={formatNumber(totalViews, locale)}
          label={t('analyticsViews')}
          hint={
            leadComparison?.view_count_change_pct != null
              ? t('analyticsPeriodChangeHint', {
                  pct: Math.round(leadComparison.view_count_change_pct * 100),
                })
              : undefined
          }
          tone={
            leadComparison?.view_count_change_pct != null &&
            leadComparison.view_count_change_pct < 0
              ? 'danger'
              : undefined
          }
        />
        <StatTile value={formatNumber(totalLikes, locale)} label={t('analyticsLikes')} />
        <StatTile value={formatNumber(totalComments, locale)} label={t('analyticsComments')} />
        <StatTile value={formatNumber(totalShares, locale)} label={t('analyticsShares')} />
        <StatTile
          value={`${Math.round(engagementRate * 1000) / 10}%`}
          label={t('analyticsEngagementRate')}
        />
        <StatTile
          value={avgFinishRate !== null ? `${Math.round(avgFinishRate * 1000) / 10}%` : '—'}
          label={t('analyticsFinishRateLabel')}
        />
      </div>

      <div className="grid grid-cols-2 gap-3 rounded-[var(--radius-md)] border border-border bg-surface p-4 sm:grid-cols-3">
        <StatTile
          value={`${summary.coverage.episodes_with_final_cut}/${summary.coverage.total_episodes}`}
          label={t('coverageFinalCutLabel')}
        />
        <StatTile
          value={String(summary.coverage.episodes_distributed)}
          label={t('coverageDistributedLabel')}
        />
        <StatTile
          value={String(summary.coverage.channels_covered.length)}
          label={t('coverageChannelsLabel')}
          hint={
            hasFollowerData ? t('coverageFollowerHint', { count: latestFollowerTotal }) : undefined
          }
        />
      </div>

      <section className="flex flex-col gap-3">
        <h3 className="text-sm font-semibold">{t('analyticsTrendTitle')}</h3>
        <div className="rounded-[var(--radius-md)] border border-border bg-surface p-4">
          <TrendChart
            data={viewsDaily.rows}
            series={viewsSeries}
            emptyTitle={t('analyticsTrendEmpty')}
          />
        </div>
      </section>

      {hasFollowerData ? (
        <section className="flex flex-col gap-3">
          <h3 className="text-sm font-semibold">{t('analyticsFollowerTrendTitle')}</h3>
          <div className="rounded-[var(--radius-md)] border border-border bg-surface p-4">
            <TrendChart
              data={followersDaily.rows}
              series={followersSeries}
              emptyTitle={t('analyticsTrendEmpty')}
            />
          </div>
        </section>
      ) : null}

      <section className="grid gap-4 lg:grid-cols-2">
        <div className="flex flex-col gap-3">
          <h3 className="text-sm font-semibold">{t('analyticsChannelCompareTitle')}</h3>
          <div className="rounded-[var(--radius-md)] border border-border bg-surface p-4">
            <BarComparisonChart
              emptyTitle={t('seriesAnalyticsOverviewEmpty')}
              data={SERIES_CHANNELS.map((channel) => {
                const total = totals.find((item) => item.channel === channel);
                return {
                  label: t(CHANNEL_LABEL_KEYS[channel] ?? channel),
                  view_count: total?.view_count ?? 0,
                  like_count: total?.like_count ?? 0,
                  comment_count: total?.comment_count ?? 0,
                  share_count: total?.share_count ?? 0,
                };
              })}
              series={[
                { dataKey: 'view_count', label: t('analyticsViews'), color: 'primary' },
                { dataKey: 'like_count', label: t('analyticsLikes'), color: 'success' },
                { dataKey: 'comment_count', label: t('analyticsComments'), color: 'amber' },
                { dataKey: 'share_count', label: t('analyticsShares'), color: 'danger' },
              ]}
            />
          </div>
        </div>
        <div className="flex flex-col gap-3">
          <h3 className="text-sm font-semibold">{t('analyticsChannelShareTitle')}</h3>
          <div className="rounded-[var(--radius-md)] border border-border bg-surface p-4">
            <ChannelSharePieChart
              emptyTitle={t('seriesAnalyticsOverviewEmpty')}
              data={totals.map((item) => ({
                label: t(CHANNEL_LABEL_KEYS[item.channel] ?? item.channel),
                value: item.view_count,
              }))}
            />
          </div>
        </div>
      </section>

      {ranking.length > 0 ? (
        <section className="flex flex-col gap-3">
          <h3 className="text-sm font-semibold">{t('analyticsRankingTitle')}</h3>
          <ol className="flex flex-col divide-y divide-border rounded-[var(--radius-md)] border border-border bg-surface">
            {ranking.map((entry, index) => (
              <li key={entry.episode_id} className="flex items-center gap-3 px-4 py-3">
                <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-surface-soft text-xs font-semibold text-muted">
                  {index + 1}
                </span>
                <span className="flex-1 text-sm">
                  {entry.episode_number}. {entry.episode_title}
                </span>
                <span className="text-sm tabular text-muted">
                  {formatNumber(entry.view_count, locale)}
                </span>
              </li>
            ))}
          </ol>
        </section>
      ) : null}

      <section className="flex flex-col gap-3">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold">{t('seriesAnalyticsDetailTitle')}</h3>
          <Button size="sm" variant="secondary" onClick={exportEpisodesCsv}>
            {t('analyticsExportCsv')}
          </Button>
        </div>
        <ChannelMetricChart
          channels={SERIES_CHANNELS}
          rows={summary.totals}
          labelForChannel={(channel) => t(CHANNEL_LABEL_KEYS[channel] ?? channel)}
          metricLabels={{
            views: t('analyticsViews'),
            likes: t('analyticsLikes'),
            comments: t('analyticsComments'),
            shares: t('analyticsShares'),
          }}
        />

        <div className="overflow-x-auto rounded-[var(--radius-md)] border border-border bg-surface">
          <table className="w-full min-w-[880px] text-left text-sm">
            <thead className="border-b border-border text-xs text-muted">
              <tr>
                <th className="px-4 py-3 font-medium">{t('seriesAnalyticsEpisodeColumn')}</th>
                <th className="px-4 py-3 font-medium">{t('seriesAnalyticsChannelColumn')}</th>
                <th className="px-4 py-3 font-medium">{t('analyticsViews')}</th>
                <th className="px-4 py-3 font-medium">{t('analyticsLikes')}</th>
                <th className="px-4 py-3 font-medium">{t('analyticsComments')}</th>
                <th className="px-4 py-3 font-medium">{t('analyticsShares')}</th>
                <th className="px-4 py-3 font-medium">{t('analyticsEngagementRate')}</th>
                <th className="px-4 py-3 font-medium">{t('analyticsFinishRateLabel')}</th>
                <th className="px-4 py-3 font-medium">{t('analyticsAvgPlayDurationLabel')}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {summary.episodes.length === 0 ? (
                <tr>
                  <td colSpan={9} className="px-4 py-6 text-center text-sm text-muted">
                    {t('seriesAnalyticsEpisodeTableEmpty')}
                  </td>
                </tr>
              ) : (
                summary.episodes.map((row) => (
                  <tr key={`${row.episode_id}-${row.channel}`}>
                    <td className="px-4 py-3 text-sm">
                      {row.episode_number}. {row.episode_title}
                    </td>
                    <td className="px-4 py-3 text-sm text-muted">
                      {t(CHANNEL_LABEL_KEYS[row.channel] ?? row.channel)}
                    </td>
                    <td className="px-4 py-3 text-sm">{row.view_count}</td>
                    <td className="px-4 py-3 text-sm">{row.like_count}</td>
                    <td className="px-4 py-3 text-sm">{row.comment_count}</td>
                    <td className="px-4 py-3 text-sm">{row.share_count}</td>
                    <td className="px-4 py-3 text-sm">
                      {Math.round(row.engagement_rate * 1000) / 10}%
                    </td>
                    <td className="px-4 py-3 text-sm">
                      {row.finish_rate !== null
                        ? `${Math.round(row.finish_rate * 1000) / 10}%`
                        : '—'}
                    </td>
                    <td className="px-4 py-3 text-sm">
                      {row.avg_play_duration_ms !== null
                        ? `${Math.round(row.avg_play_duration_ms / 1000)}s`
                        : '—'}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
