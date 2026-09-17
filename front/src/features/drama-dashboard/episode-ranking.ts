import type { SeriesMetricsEpisodeRow } from './distribution-api';

export interface EpisodeRankingEntry {
  episode_id: string;
  episode_number: number;
  episode_title: string;
  view_count: number;
  like_count: number;
  comment_count: number;
  share_count: number;
}

/**
 * Collapses the per-episode × per-channel rows the detail page's table
 * already has into one entry per episode (summed across every channel it's
 * published on), sorted by total plays descending — the "分集播放排行"
 * list. Pure aggregation over data the page already fetched, no extra
 * network call.
 */
export function rankEpisodesByViews(rows: SeriesMetricsEpisodeRow[]): EpisodeRankingEntry[] {
  const byEpisode = new Map<string, EpisodeRankingEntry>();
  for (const row of rows) {
    const entry = byEpisode.get(row.episode_id);
    if (entry) {
      entry.view_count += row.view_count;
      entry.like_count += row.like_count;
      entry.comment_count += row.comment_count;
      entry.share_count += row.share_count;
    } else {
      byEpisode.set(row.episode_id, {
        episode_id: row.episode_id,
        episode_number: row.episode_number,
        episode_title: row.episode_title,
        view_count: row.view_count,
        like_count: row.like_count,
        comment_count: row.comment_count,
        share_count: row.share_count,
      });
    }
  }
  return Array.from(byEpisode.values()).sort((a, b) => b.view_count - a.view_count);
}
