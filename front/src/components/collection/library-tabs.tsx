'use client';

import { useTranslations } from 'next-intl';
import { useState } from 'react';

import { Poster } from '@/components/media/poster';
import { WorkCard } from '@/components/work/work-card';
import { IconPlus } from '@/components/ui/icons';
import { EmptyState } from '@/components/ui/primitives';
import { Link } from '@/i18n/navigation';
import type { Draft, WorkSummary } from '@/lib/api/types';
import { cn } from '@/lib/cn';

const TABS = ['all', 'published', 'drafts', 'private', 'bookmarks'] as const;
type Tab = (typeof TABS)[number];

/**
 * Tabbed library.
 *
 * Client-side because all five buckets come from the same three requests the
 * server already made; refetching per tab would be slower and would lose the
 * scroll position.
 */
export function LibraryTabs({
  initialTab,
  works,
  published,
  privateWorks,
  drafts,
  bookmarks,
}: {
  initialTab?: string;
  works: WorkSummary[];
  published: WorkSummary[];
  privateWorks: WorkSummary[];
  drafts: Draft[];
  bookmarks: WorkSummary[];
}) {
  const t = useTranslations('collectionPage');
  const tVisibility = useTranslations('visibility');
  const [tab, setTab] = useState<Tab>(
    TABS.includes(initialTab as Tab) ? (initialTab as Tab) : 'all',
  );

  const labels: Record<Tab, string> = {
    all: t('tabAll'),
    published: t('tabPublished'),
    drafts: t('tabDrafts'),
    private: t('tabPrivate'),
    bookmarks: t('tabBookmarks'),
  };

  const shownWorks =
    tab === 'published'
      ? published
      : tab === 'private'
        ? privateWorks
        : tab === 'bookmarks'
          ? bookmarks
          : works;
  const shownDrafts = tab === 'all' || tab === 'drafts' ? drafts : [];
  const empty = shownWorks.length === 0 && shownDrafts.length === 0;

  return (
    <div>
      <div role="tablist" aria-label={t('title')} className="flex gap-6 border-b border-border">
        {TABS.map((id) => (
          <button
            key={id}
            role="tab"
            type="button"
            aria-selected={tab === id}
            onClick={() => setTab(id)}
            className={cn(
              '-mb-px border-b-2 pb-3 text-sm transition-colors',
              tab === id
                ? 'border-primary text-text'
                : 'border-transparent text-muted hover:text-text',
            )}
          >
            {labels[id]}
          </button>
        ))}
      </div>

      <div className="mt-6">
        {empty ? (
          <EmptyState title={t('empty')} description={t('emptyHint')} />
        ) : (
          <ul className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {shownDrafts.map((draft) => (
              <li key={draft.id}>
                <Link href={`/publish/${draft.id}`} className="block">
                  <Poster
                    src={draft.output_url}
                    alt={draft.title ?? t('tabDrafts')}
                    className="border border-border"
                  >
                    <span className="absolute right-2 top-2 rounded-md border border-border bg-surface/90 px-2 py-0.5 text-[11px]">
                      {tVisibility('draft')}
                    </span>
                  </Poster>
                  <p className="mt-2 truncate text-sm font-medium">
                    {draft.title ?? t('tabDrafts')}
                  </p>
                </Link>
              </li>
            ))}

            {shownWorks.map((work) => (
              <li key={work.id}>
                <WorkCard
                  work={work}
                  badge={{
                    label: tVisibility(work.visibility),
                    tone: work.visibility.startsWith('public') ? 'success' : 'neutral',
                  }}
                />
              </li>
            ))}

            {tab === 'all' || tab === 'drafts' ? (
              <li>
                <Link
                  href="/create"
                  className="flex aspect-video flex-col items-center justify-center gap-2 rounded-[var(--radius-md)] border border-dashed border-border text-center transition-colors hover:border-border-strong hover:bg-surface-soft"
                >
                  <IconPlus className="size-5 text-muted" />
                  <span className="text-sm font-medium">{t('createNew')}</span>
                  <span className="px-4 text-xs text-muted">{t('createNewHint')}</span>
                </Link>
              </li>
            ) : null}
          </ul>
        )}
      </div>
    </div>
  );
}
