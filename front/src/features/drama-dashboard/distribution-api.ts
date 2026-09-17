import { api, newIdempotencyKey } from '@/lib/api/client';

export interface ConfigStatus {
  douyin: boolean;
  kuaishou: boolean;
}

export interface PlatformAccountLink {
  id: string;
  channel: string;
  external_account_id: string;
  external_account_label: string | null;
  status: string;
  connected_at: string;
  token_expires_at: string | null;
}

export interface PublicationFanoutItem {
  channel: string;
  status: string;
  external_post_id: string | null;
  error: string | null;
  reason: string | null;
}

export interface PublicationFanoutResult {
  work_id: string;
  results: PublicationFanoutItem[];
}

export interface SeriesMetricsChannelTotal {
  channel: string;
  view_count: number;
  like_count: number;
  comment_count: number;
  share_count: number;
  like_rate: number;
  comment_rate: number;
  share_rate: number;
  engagement_rate: number;
}

export interface SeriesMetricsEpisodeRow {
  episode_id: string;
  episode_number: number;
  episode_title: string;
  channel: string;
  view_count: number;
  like_count: number;
  comment_count: number;
  share_count: number;
  like_rate: number;
  comment_rate: number;
  share_rate: number;
  engagement_rate: number;
  finish_rate: number | null;
  avg_play_duration_ms: number | null;
  fetched_at: string;
}

export interface SeriesMetricsDailyPoint {
  date: string;
  channel: string;
  view_count: number;
  like_count: number;
  comment_count: number;
  share_count: number;
}

export interface SeriesFollowerDailyPoint {
  date: string;
  channel: string;
  follower_count: number;
}

export interface SeriesMetricsPeriodComparison {
  channel: string;
  view_count_change_pct: number | null;
  like_count_change_pct: number | null;
  comment_count_change_pct: number | null;
  share_count_change_pct: number | null;
}

export interface SeriesDistributionCoverage {
  total_episodes: number;
  episodes_with_final_cut: number;
  episodes_distributed: number;
  channels_covered: string[];
}

export interface SeriesMetricsSummary {
  totals: SeriesMetricsChannelTotal[];
  episodes: SeriesMetricsEpisodeRow[];
  daily: SeriesMetricsDailyPoint[];
  followers: SeriesFollowerDailyPoint[];
  period_comparison: SeriesMetricsPeriodComparison[];
  coverage: SeriesDistributionCoverage;
}

export function getConfigStatus() {
  return api.get<ConfigStatus>('/v1/platform-accounts/config-status');
}

export function getAuthorizeUrl(channel: string) {
  return api.get<{ authorize_url: string }>(`/v1/platform-accounts/${channel}/connect`);
}

export function completeConnect(channel: string, code: string, state: string) {
  return api.get<PlatformAccountLink>(
    `/v1/platform-accounts/${channel}/callback?code=${encodeURIComponent(code)}&state=${encodeURIComponent(state)}`,
  );
}

export function listPlatformAccounts() {
  return api.get<PlatformAccountLink[]>('/v1/platform-accounts');
}

export function disconnectPlatformAccount(linkId: string) {
  return api.delete<PlatformAccountLink>(`/v1/platform-accounts/${linkId}`);
}

export function getSeriesMetrics(seriesId: string, days = 30) {
  return api.get<SeriesMetricsSummary>(`/v1/drama-series/${seriesId}/metrics`, {
    query: { days },
  });
}

export function publishFanout(
  workId: string,
  input: { channels: string[]; title: string; description?: string; hashtags?: string[] },
) {
  return api.post<PublicationFanoutResult>(`/v1/works/${workId}/publications:fanout`, input, {
    idempotencyKey: newIdempotencyKey(),
  });
}
