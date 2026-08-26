import { getTranslations } from 'next-intl/server';

import { Poster } from '@/components/media/poster';
import { EmptyState, SectionHeading } from '@/components/ui/primitives';
import { Link } from '@/i18n/navigation';
import type { Series } from '@/lib/api/types';

const VISIBLE_LIMIT = 4;

/**
 * "Recent series": the quick way back into a short-drama in progress.
 *
 * Sits above the shortform hero banner so a returning creator sees "continue
 * episode N" before "start something new". The list is already sorted by
 * the API for recent activity (`GET /v1/series`), so this only slices the
 * head rather than re-sorting.
 */
export async function RecentSeries({ series }: { series: Series[] | null }) {
  const t = await getTranslations('createPage');
  const tActions = await getTranslations('actions');

  // `null` means the visitor is signed out — nothing here for them to
  // continue, so the whole rail disappears instead of showing an empty one.
  if (series === null) return null;

  return (
    <section>
      <SectionHeading
        title={t('recentSeriesTitle')}
        description={t('recentSeriesHint')}
        action={
          series.length > 0 ? (
            <Link href="/create/short/studio" className="text-xs text-muted hover:text-text">
              {tActions('viewAll')}
            </Link>
          ) : null
        }
      />

      {series.length === 0 ? (
        <EmptyState
          title={t('noSeries')}
          description={t('noSeriesHint')}
          action={
            <Link
              href="/create/short/studio"
              className="rounded-[var(--radius-sm)] border border-border px-4 py-2 text-sm transition-colors hover:border-border-strong hover:bg-surface-soft"
            >
              {t('startShortformStudio')}
            </Link>
          }
        />
      ) : (
        <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {series.slice(0, VISIBLE_LIMIT).map((item) => (
            <li
              key={item.id}
              className="flex flex-col overflow-hidden rounded-[var(--radius-md)] border border-border bg-surface transition-shadow hover:shadow-raised"
            >
              <Poster
                src={item.latest_episode?.cover_url}
                alt={item.latest_episode?.title ?? item.title}
                aspect="video"
              />
              <div className="flex flex-1 flex-col p-4">
                <h3 className="truncate text-sm font-semibold">{item.title}</h3>
                <p className="mt-1 text-xs text-muted">
                  {t('episodeCount', { count: item.episode_count })}
                </p>
                <Link
                  href={{ pathname: '/create/short/studio', query: { seriesId: item.id } }}
                  className="mt-4 flex w-full items-center justify-center gap-2 rounded-[var(--radius-sm)] border border-border px-3 py-2 text-xs transition-colors hover:border-border-strong hover:bg-surface-soft"
                >
                  {t('continueEpisode', { number: (item.latest_episode?.episode_number ?? 0) + 1 })}
                </Link>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
