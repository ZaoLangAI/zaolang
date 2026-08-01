import { getTranslations } from 'next-intl/server';

import { WorkInfoPanel } from '@/components/work/work-info-panel';
import { WorkRail } from '@/components/work/work-rail';
import { WorkStage } from '@/components/work/work-stage';
import { EmptyState, SectionHeading } from '@/components/ui/primitives';
import { TagFilter } from '@/components/discover/tag-filter';
import { serverFetch, serverFetchOrNull } from '@/lib/api/server';
import type { Page, Tag, WorkDetail, WorkSummary } from '@/lib/api/types';

export async function generateMetadata() {
  const t = await getTranslations('discover');
  return { title: t('title'), description: t('subtitle') };
}

export default async function DiscoverPage({
  searchParams,
}: {
  searchParams: Promise<{ tag?: string; sort?: string }>;
}) {
  const { tag, sort } = await searchParams;
  const t = await getTranslations('discover');

  const [feed, tags] = await Promise.all([
    serverFetch<Page<WorkSummary>>('/v1/works', {
      query: { tag, sort: sort ?? 'popular', limit: 24 },
    }),
    serverFetch<Page<Tag>>('/v1/tags', { query: { limit: 24 }, revalidate: 300 }),
  ]);

  // The stage shows the most prominent work in full; the rail below carries
  // the rest. Fetching the detail separately is what gives the panel its
  // lineage, licence and reusable parameters.
  const featured = feed.items[0]
    ? await serverFetchOrNull<WorkDetail>(`/v1/works/${feed.items[0].id}`, { authenticated: true })
    : null;

  const rail = feed.items.slice(featured ? 1 : 0);

  if (!featured) {
    return (
      <div className="mx-auto w-full max-w-[1440px] px-4 py-16 sm:px-6">
        <EmptyState title={t('emptyFeed')} description={t('emptyFeedHint')} />
      </div>
    );
  }

  return (
    <div className="mx-auto flex w-full max-w-[1440px] flex-col gap-8 px-4 py-6 sm:px-6">
      <section className="grid gap-6 lg:grid-cols-[minmax(0,1.72fr)_minmax(0,1fr)]">
        <WorkStage work={featured} />
        <aside className="rounded-[var(--radius-lg)] border border-border bg-surface p-5 lg:p-6">
          <WorkInfoPanel work={featured} compact />
        </aside>
      </section>

      <section>
        <SectionHeading title={t('inspiration')} description={t('inspirationHint')} />
        <TagFilter tags={tags.items} active={tag} />
        <div className="mt-5">
          {rail.length > 0 ? (
            <WorkRail works={rail} />
          ) : (
            <EmptyState title={t('noResults')} description={t('noResultsHint')} />
          )}
        </div>
      </section>
    </div>
  );
}
