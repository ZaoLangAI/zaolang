'use client';

import { useTranslations } from 'next-intl';
import { useEffect, useState } from 'react';

import { api } from '@/lib/api/client';

const CHANNEL_LABEL_KEYS: Record<string, string> = {
  douyin: 'channelDouyin',
  kuaishou: 'channelKuaishou',
};

interface EpisodeExternalMetric {
  channel: string;
  external_post_id: string;
  view_count: number;
  like_count: number;
  comment_count: number;
  share_count: number;
  fetched_at: string;
}

/**
 * Read-only playback/engagement snapshot for a published work, pulled
 * periodically off the platform's own metrics endpoint (see
 * `app.workers.tasks.pull_episode_metrics`). No manual refresh here on
 * purpose — that would need a synchronous external call in the request
 * path, which this phase deliberately avoids.
 */
export function AnalyticsPanel({ workId }: { workId: string }) {
  const t = useTranslations('editor');
  const [metrics, setMetrics] = useState<EpisodeExternalMetric[]>([]);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    void api
      .get<EpisodeExternalMetric[]>(`/v1/works/${workId}/metrics`)
      .then((rows) => {
        setMetrics(rows);
        setLoaded(true);
      })
      .catch(() => setLoaded(true));
  }, [workId]);

  if (!loaded || metrics.length === 0) {
    return (
      <div className="rounded-[var(--radius-md)] border border-border bg-surface p-4">
        <h3 className="text-sm font-semibold">{t('analyticsPanelTitle')}</h3>
        <p className="mt-2 text-xs text-muted">{t('analyticsEmpty')}</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3 rounded-[var(--radius-md)] border border-border bg-surface p-4">
      <h3 className="text-sm font-semibold">{t('analyticsPanelTitle')}</h3>
      <ul className="flex flex-col gap-3">
        {metrics.map((metric) => (
          <li key={`${metric.channel}-${metric.external_post_id}`} className="text-xs">
            <p className="font-medium">{t(CHANNEL_LABEL_KEYS[metric.channel] ?? metric.channel)}</p>
            <div className="mt-1 grid grid-cols-4 gap-2 text-muted">
              <span>
                {t('analyticsViews')}: {metric.view_count}
              </span>
              <span>
                {t('analyticsLikes')}: {metric.like_count}
              </span>
              <span>
                {t('analyticsComments')}: {metric.comment_count}
              </span>
              <span>
                {t('analyticsShares')}: {metric.share_count}
              </span>
            </div>
            <p className="mt-1 text-muted">
              {t('analyticsLastUpdated', { time: new Date(metric.fetched_at).toLocaleString() })}
            </p>
          </li>
        ))}
      </ul>
    </div>
  );
}
