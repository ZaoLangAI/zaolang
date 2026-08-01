import { getLocale, getTranslations } from 'next-intl/server';

import { IconBookmark, IconCheck, IconRemix } from '@/components/ui/icons';
import type { Locale } from '@/i18n/routing';
import type { GenerationJob, WorkSummary } from '@/lib/api/types';
import { formatRelative } from '@/lib/format';

interface Entry {
  key: string;
  at: string;
  icon: React.ReactNode;
  title: string;
  hint?: string;
}

/**
 * Recent activity, assembled from records that already exist.
 *
 * There is no activity table; inventing one would mean a second source of
 * truth for things the works, bookmarks and jobs already say. Only the
 * owner sees their own jobs, since a job is not public until it is published.
 */
export async function ActivityFeed({
  works,
  bookmarks,
  jobs,
}: {
  works: WorkSummary[];
  bookmarks: WorkSummary[];
  jobs: GenerationJob[];
}) {
  const t = await getTranslations('profilePage');
  const tRemix = await getTranslations('remixPage');
  const locale = (await getLocale()) as Locale;

  const tierLabel: Record<string, string> = {
    preview: tRemix('tierPreview'),
    standard: tRemix('tierStandard'),
    cinematic: tRemix('tierCinematic'),
  };

  const entries: Entry[] = [
    ...works
      .filter((work) => work.published_at)
      .map((work) => ({
        key: `work-${work.id}`,
        at: work.published_at!,
        icon: <IconCheck className="size-3.5 text-success" />,
        title: t('activityPublished', { title: work.title }),
        hint: t('activityPublishedHint'),
      })),
    ...bookmarks.map((work) => ({
      key: `bookmark-${work.id}`,
      at: work.published_at ?? '',
      icon: <IconBookmark className="size-3.5 text-muted" />,
      title: t('activityBookmarked', { title: work.title }),
    })),
    ...jobs.map((job) => ({
      key: `job-${job.id}`,
      at: job.created_at,
      icon: <IconRemix className="size-3.5 text-primary" />,
      title: t('activityJob', { tier: tierLabel[job.quality_tier] ?? job.quality_tier }),
      hint: t('activityJobHint', { credits: job.actual_credits ?? job.quoted_credits }),
    })),
  ]
    .filter((entry) => entry.at)
    .sort((a, b) => new Date(b.at).getTime() - new Date(a.at).getTime())
    .slice(0, 8);

  return (
    <section className="rounded-[var(--radius-md)] border border-border bg-surface">
      <h2 className="border-b border-border px-5 py-4 text-base font-semibold">
        {t('recentActivity')}
      </h2>
      {entries.length === 0 ? (
        <p className="px-5 py-8 text-center text-sm text-muted">{t('noActivity')}</p>
      ) : (
        <ol className="divide-y divide-border">
          {entries.map((entry) => (
            <li key={entry.key} className="flex gap-3 px-5 py-4">
              <span className="mt-0.5 shrink-0">{entry.icon}</span>
              <div className="min-w-0">
                <p className="truncate text-sm">{entry.title}</p>
                <p className="mt-0.5 text-xs text-muted">
                  {entry.hint ? `${entry.hint} · ` : ''}
                  {formatRelative(entry.at, locale)}
                </p>
              </div>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
