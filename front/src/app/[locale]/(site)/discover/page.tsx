import { getTranslations } from 'next-intl/server';
import { Suspense } from 'react';

import { DiscoverHeroSkeleton } from '@/components/discover/hero-skeleton';
import { InspirationMasonry } from '@/components/discover/inspiration-masonry';
import { InspirationSkeleton } from '@/components/discover/inspiration-skeleton';
import { TagFilter } from '@/components/discover/tag-filter';
import { WorkInfoPanel } from '@/components/work/work-info-panel';
import { WorkStage } from '@/components/work/work-stage';
import { EmptyState, SectionHeading } from '@/components/ui/primitives';
import { serverFetch, serverFetchOrNull } from '@/lib/api/server';
import type { Page, Tag, WorkDetail, WorkSummary } from '@/lib/api/types';

/**
 * Tiles per request. Enough to fill the widest column layout twice over, small
 * enough that the first paint is not waiting on a hundred summaries; the rest
 * arrives as the wall is scrolled.
 */
const PAGE_SIZE = 20;

interface Filters {
  q?: string;
  tag?: string;
  sort?: string;
}

export async function generateMetadata() {
  const t = await getTranslations('discover');
  return { title: t('title'), description: t('subtitle') };
}

export default async function DiscoverPage({ searchParams }: { searchParams: Promise<Filters> }) {
  const { q, tag, sort } = await searchParams;
  const filters: Filters = { q: q?.trim() || undefined, tag, sort: sort ?? 'popular' };

  // Two boundaries rather than one: the hero needs a second round trip for the
  // work detail, and holding the whole page for it would leave the wall behind
  // a skeleton it does not depend on.
  return (
    <div className="mx-auto flex w-full max-w-[1440px] flex-col gap-8 px-4 py-6 sm:px-6">
      <Suspense fallback={<DiscoverHeroSkeleton />}>
        <DiscoverHero filters={filters} />
      </Suspense>

      <Suspense fallback={<InspirationSkeleton />}>
        <InspirationSection filters={filters} />
      </Suspense>
    </div>
  );
}

async function DiscoverHero({ filters }: { filters: Filters }) {
  const feed = await serverFetch<Page<WorkSummary>>('/v1/works', {
    query: { ...filters, limit: 1 },
  });

  // The stage shows the most prominent work in full. Fetching the detail
  // separately is what gives the panel its lineage, licence and reusable
  // parameters. Public fetch keeps the hero cacheable — like/bookmark state is
  // filled in by the client session.
  const featured = feed.items[0]
    ? await serverFetchOrNull<WorkDetail>(`/v1/works/${feed.items[0].id}`)
    : null;
  if (!featured) return null;

  return (
    <section className="grid gap-6 lg:grid-cols-[minmax(0,1.72fr)_minmax(0,1fr)]">
      <WorkStage work={featured} lazyMedia />
      {/* See the same `min-w-0` on the work page: the lineage strip inside is a
          sideways scroller, and a grid item's `min-width: auto` would let its
          intrinsic width widen the track past the viewport. */}
      <aside className="min-w-0 rounded-[var(--radius-lg)] border border-border bg-surface p-5 lg:p-6">
        <WorkInfoPanel work={featured} compact />
      </aside>
    </section>
  );
}

async function InspirationSection({ filters }: { filters: Filters }) {
  const t = await getTranslations('discover');
  const filtered = Boolean(filters.q || filters.tag);

  const [feed, tags] = await Promise.all([
    serverFetch<Page<WorkSummary>>('/v1/works', {
      query: { ...filters, limit: PAGE_SIZE },
    }),
    serverFetch<Page<Tag>>('/v1/tags', { query: { limit: 24 }, revalidate: 300 }),
  ]);

  // The hero runs the same query with `limit: 1`, so the first item is already
  // on screen above the wall. The cursor still points at the last item of the
  // full page, so dropping this one leaves no gap.
  const tiles = feed.items.slice(1);

  return (
    <section>
      <SectionHeading title={t('inspiration')} description={t('inspirationHint')} />
      <TagFilter tags={tags.items} active={filters.tag} q={filters.q} sort={filters.sort} />
      <div className="mt-5">
        {tiles.length > 0 ? (
          <InspirationMasonry
            // Remount on a filter change: the appended pages belong to the old
            // query and there is nothing to reconcile them with.
            key={`${filters.q ?? ''}|${filters.tag ?? ''}|${filters.sort ?? ''}`}
            works={tiles}
            cursor={feed.next_cursor ?? null}
            query={filters}
            pageSize={PAGE_SIZE}
          />
        ) : null}
        {feed.items.length === 0 ? (
          <EmptyState
            title={filtered ? t('noResults') : t('emptyFeed')}
            description={filtered ? t('noResultsHint') : t('emptyFeedHint')}
          />
        ) : null}
      </div>
    </section>
  );
}
