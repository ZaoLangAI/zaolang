import { Skeleton } from '@/components/ui/primitives';

export interface ChannelMetricRow {
  channel: string;
  view_count: number;
  like_count: number;
  comment_count: number;
  share_count: number;
}

/**
 * Hand-rolled per-channel comparison: a views bar plus the other three
 * metrics as plain numbers underneath. Kept deliberately simple for the
 * single-episode "播放数据" panel (`analytics-panel.tsx`) — the series-level
 * pages use the `recharts`-based `BarComparisonChart`/`ChannelSharePieChart`
 * instead, where a richer visual actually earns its keep. Always renders
 * every channel in `channels`, even when `rows` has no matching entry — a
 * missing channel gets a flat, muted bar and a `placeholder` ("—") in place
 * of every number, so the section never collapses to a single line of text.
 */
export function ChannelMetricChart({
  channels,
  rows,
  labelForChannel,
  metricLabels,
  placeholder = '—',
}: {
  channels: readonly string[];
  rows: ChannelMetricRow[];
  labelForChannel: (channel: string) => string;
  metricLabels: { views: string; likes: string; comments: string; shares: string };
  placeholder?: string;
}) {
  const rowsByChannel = new Map(rows.map((row) => [row.channel, row]));
  const maxViews = Math.max(1, ...rows.map((row) => row.view_count));

  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {channels.map((channel) => {
        const row = rowsByChannel.get(channel);
        const hasData = row !== undefined;
        return (
          <div
            key={channel}
            className="rounded-[var(--radius-sm)] border border-border bg-surface-soft p-3"
          >
            <p className="text-xs font-medium text-muted">{labelForChannel(channel)}</p>
            <div className="mt-2 h-2 w-full overflow-hidden rounded-full bg-border/50">
              {hasData ? (
                <div
                  className="h-full rounded-full bg-primary"
                  style={{ width: `${Math.round((row.view_count / maxViews) * 100)}%` }}
                />
              ) : null}
            </div>
            <div className="mt-2 grid grid-cols-2 gap-1 text-xs text-text">
              <span>
                {metricLabels.views}: {hasData ? row.view_count : placeholder}
              </span>
              <span>
                {metricLabels.likes}: {hasData ? row.like_count : placeholder}
              </span>
              <span>
                {metricLabels.comments}: {hasData ? row.comment_count : placeholder}
              </span>
              <span>
                {metricLabels.shares}: {hasData ? row.share_count : placeholder}
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

/** Dimension-matched loading placeholder for {@link ChannelMetricChart}, so
 *  swapping skeleton for real content causes no layout shift. */
export function ChannelMetricChartSkeleton({ channelCount }: { channelCount: number }) {
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {Array.from({ length: channelCount }).map((_, index) => (
        <div
          key={index}
          className="rounded-[var(--radius-sm)] border border-border bg-surface-soft p-3"
        >
          <Skeleton className="h-3 w-16" />
          <Skeleton className="mt-2 h-2 w-full rounded-full" />
          <div className="mt-2 grid grid-cols-2 gap-1">
            <Skeleton className="h-3 w-full" />
            <Skeleton className="h-3 w-full" />
            <Skeleton className="h-3 w-full" />
            <Skeleton className="h-3 w-full" />
          </div>
        </div>
      ))}
    </div>
  );
}
