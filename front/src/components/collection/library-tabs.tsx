'use client';

import { useLocale, useTranslations } from 'next-intl';
import { useState } from 'react';

import { CreateCollectionDialog } from '@/components/collection/create-collection-dialog';
import { Poster } from '@/components/media/poster';
import { CreateSkillDialog } from '@/components/skills/create-skill-dialog';
import { ManageSkillDialog } from '@/components/skills/manage-skill-dialog';
import { SkillCard } from '@/components/skills/skill-card';
import { WorkCard } from '@/components/work/work-card';
import { IconPlus } from '@/components/ui/icons';
import { EmptyState } from '@/components/ui/primitives';
import { Link, useRouter } from '@/i18n/navigation';
import type { Locale } from '@/i18n/routing';
import type { Collection, CreationSkillSummary, Draft, WorkSummary } from '@/lib/api/types';
import { cn } from '@/lib/cn';

const TABS = ['all', 'published', 'drafts', 'private', 'bookmarks', 'collections', 'skills'] as const;
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
  collections,
  skills,
}: {
  initialTab?: string;
  works: WorkSummary[];
  published: WorkSummary[];
  privateWorks: WorkSummary[];
  drafts: Draft[];
  bookmarks: WorkSummary[];
  collections: Collection[];
  skills: CreationSkillSummary[];
}) {
  const t = useTranslations('collectionPage');
  const tVisibility = useTranslations('visibility');
  const locale = useLocale() as Locale;
  const router = useRouter();
  const [tab, setTab] = useState<Tab>(
    TABS.includes(initialTab as Tab) ? (initialTab as Tab) : 'all',
  );
  const [createOpen, setCreateOpen] = useState(false);
  const [createSkillOpen, setCreateSkillOpen] = useState(false);
  const [managingSkill, setManagingSkill] = useState<CreationSkillSummary | null>(null);

  const labels: Record<Tab, string> = {
    all: t('tabAll'),
    published: t('tabPublished'),
    drafts: t('tabDrafts'),
    private: t('tabPrivate'),
    bookmarks: t('tabBookmarks'),
    collections: t('tabCollections'),
    skills: t('tabSkills'),
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
        {tab === 'collections' ? (
          <>
            <ul className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
              {collections.map((collection) => (
                <li key={collection.id}>
                  <CollectionTile collection={collection} label={t('collectionItems', { count: collection.item_count })} />
                </li>
              ))}
              <li>
                <button
                  type="button"
                  onClick={() => setCreateOpen(true)}
                  className="flex aspect-video w-full flex-col items-center justify-center gap-2 rounded-[var(--radius-md)] border border-dashed border-border text-center transition-colors hover:border-border-strong hover:bg-surface-soft"
                >
                  <IconPlus className="size-5 text-muted" />
                  <span className="text-sm font-medium">{t('newCollection')}</span>
                </button>
              </li>
            </ul>
            {collections.length === 0 ? (
              <p className="mt-4 text-xs text-muted">{t('emptyCollectionsHint')}</p>
            ) : null}
          </>
        ) : tab === 'skills' ? (
          <>
            <ul className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
              {skills.map((skill) => (
                <SkillCard
                  key={skill.id}
                  skill={skill}
                  locale={locale}
                  showStatus
                  onClick={() => setManagingSkill(skill)}
                />
              ))}
              <li>
                <button
                  type="button"
                  onClick={() => setCreateSkillOpen(true)}
                  className="flex aspect-video w-full flex-col items-center justify-center gap-2 rounded-[var(--radius-md)] border border-dashed border-border text-center transition-colors hover:border-border-strong hover:bg-surface-soft"
                >
                  <IconPlus className="size-5 text-muted" />
                  <span className="text-sm font-medium">{t('newSkill')}</span>
                </button>
              </li>
            </ul>
            {skills.length === 0 ? (
              <p className="mt-4 text-xs text-muted">{t('emptySkillsHint')}</p>
            ) : null}
          </>
        ) : empty ? (
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

      <CreateCollectionDialog
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={() => {
          setCreateOpen(false);
          router.refresh();
        }}
      />

      <CreateSkillDialog
        open={createSkillOpen}
        onClose={() => setCreateSkillOpen(false)}
        onCreated={() => {
          setCreateSkillOpen(false);
          router.refresh();
        }}
      />

      {managingSkill ? (
        <ManageSkillDialog
          skill={managingSkill}
          onClose={() => setManagingSkill(null)}
          onChanged={() => {
            setManagingSkill(null);
            router.refresh();
          }}
        />
      ) : null}
    </div>
  );
}

/**
 * A named collection has no items endpoint, so this is a collage of whatever
 * covers the list response already included — never a link to a detail page
 * that cannot exist yet.
 */
function CollectionTile({ collection, label }: { collection: Collection; label: string }) {
  const covers = collection.cover_urls ?? [];

  return (
    <div className="flex flex-col gap-2.5">
      <div className="grid aspect-video grid-cols-2 grid-rows-2 gap-0.5 overflow-hidden rounded-[var(--radius-md)] border border-border bg-surface-soft">
        {covers.length > 0 ? (
          covers
            .slice(0, 4)
            .map((url, index) => (
              <Poster
                key={`${collection.id}-${index}`}
                src={url}
                alt={collection.name}
                aspect="fill"
                className="h-full w-full rounded-none border-0"
              />
            ))
        ) : (
          <div className="col-span-2 row-span-2 grid place-items-center text-xs text-muted">
            {collection.name}
          </div>
        )}
      </div>
      <div className="min-w-0">
        <p className="truncate text-sm font-medium">{collection.name}</p>
        <p className="mt-0.5 text-xs text-muted">{label}</p>
      </div>
    </div>
  );
}
