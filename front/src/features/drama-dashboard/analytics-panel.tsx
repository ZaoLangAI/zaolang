'use client';

import { useTranslations } from 'next-intl';

import { Button } from '@/components/ui/button';
import { IconRefresh } from '@/components/ui/icons';
import { ErrorNotice } from '@/components/ui/primitives';
import { useResource } from '@/lib/use-resource';

import { ChannelMetricChart, ChannelMetricChartSkeleton } from './channel-metric-chart';
import { CHANNEL_LABEL_KEYS, WORK_CHANNELS } from './channels';

interface EpisodeExternalMetric {
  channel: string;
  external_post_id: string;
  view_count: number;
  like_count: number;
  comment_count: number;
  share_count: number;
  finish_rate: number | null;
  avg_play_duration_ms: number | null;
  fetched_at: string;
}

/**
 * Read-only playback/engagement snapshot for a published work, pulled
 * periodically off the platform's own metrics endpoint (see
 * `app.workers.tasks.pull_episode_metrics`). No manual refresh here on
 * purpose — that would need a synchronous external call in the request
 * path, which this phase deliberately avoids. (A failed *fetch* of already-
 * pulled metrics can still be retried — see the `failed` branch below.)
 * Always renders the full chart+metrics layout, even with zero data — see
 * `ChannelMetricChart`.
 */
export function AnalyticsPanel({ workId }: { workId: string }) {
  const t = useTranslations('editor');
  const tActions = useTranslations('actions');
  const resource = useResource<EpisodeExternalMetric[]>(`/v1/works/${workId}/metrics`);

  if (resource.status === 'idle' || resource.status === 'loading') {
    return (
      <div className="rounded-[var(--radius-md)] border border-border bg-surface p-4">
        <h3 className="text-sm font-semibold">{t('analyticsPanelTitle')}</h3>
        <div className="mt-2">
          <ChannelMetricChartSkeleton channelCount={WORK_CHANNELS.length} />
        </div>
      </div>
    );
  }

  if (resource.status === 'failed') {
    return (
      <div className="rounded-[var(--radius-md)] border border-border bg-surface p-4">
        <h3 className="text-sm font-semibold">{t('analyticsPanelTitle')}</h3>
        <div className="mt-2">
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
      </div>
    );
  }

  const metrics = resource.data ?? [];

  return (
    <div className="flex flex-col gap-3 rounded-[var(--radius-md)] border border-border bg-surface p-4">
      <div>
        <h3 className="text-sm font-semibold">{t('analyticsPanelTitle')}</h3>
        {metrics.length === 0 ? (
          <p className="mt-1 text-xs text-muted">{t('analyticsEmpty')}</p>
        ) : null}
      </div>
      <ChannelMetricChart
        channels={WORK_CHANNELS}
        rows={metrics}
        labelForChannel={(channel) => t(CHANNEL_LABEL_KEYS[channel] ?? channel)}
        metricLabels={{
          views: t('analyticsViews'),
          likes: t('analyticsLikes'),
          comments: t('analyticsComments'),
          shares: t('analyticsShares'),
        }}
      />
      {metrics.length > 0 ? (
        <ul className="flex flex-col gap-1">
          {metrics.map((metric) => (
            <li key={`${metric.channel}-${metric.external_post_id}`} className="text-xs text-muted">
              {t(CHANNEL_LABEL_KEYS[metric.channel] ?? metric.channel)}
              {' · '}
              {t('analyticsLastUpdated', { time: new Date(metric.fetched_at).toLocaleString() })}
              {metric.finish_rate !== null ? (
                <>
                  {' · '}
                  {t('analyticsFinishRate', { rate: Math.round(metric.finish_rate * 100) })}
                </>
              ) : null}
              {metric.avg_play_duration_ms !== null ? (
                <>
                  {' · '}
                  {t('analyticsAvgPlayDuration', {
                    seconds: Math.round(metric.avg_play_duration_ms / 1000),
                  })}
                </>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
