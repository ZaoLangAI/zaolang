import { getTranslations } from 'next-intl/server';
import { Suspense } from 'react';

import { DiscoverHeroSkeleton } from '@/components/discover/hero-skeleton';
import { HeroCarousel } from '@/components/discover/hero-carousel';
import { InspirationMasonry } from '@/components/discover/inspiration-masonry';
import { InspirationSkeleton } from '@/components/discover/inspiration-skeleton';
import { DiscoverAccess, DiscoverSort, TagFilter } from '@/components/discover/tag-filter';
import { EmptyState, SectionHeading } from '@/components/ui/primitives';
import { serverFetchOrNull } from '@/lib/api/server';
import type { Page, Tag, WorkDetail, WorkSummary } from '@/lib/api/types';

/**
 * Tiles per request. Enough to fill the widest column layout twice over, small
 * enough that the first paint is not waiting on a hundred summaries; the rest
 * arrives as the wall is scrolled.
 */
const PAGE_SIZE = 20;

/** Cards in the pinned carousel — enough to feel like a rotation, not so many the hero outweighs the wall below it. */
const HERO_SLIDES = 6;

interface Filters {
  q?: string;
  tag?: string;
  sort?: string;
  access?: string;
}

export async function generateMetadata() {
  const t = await getTranslations('discover');
  return { title: t('title'), description: t('subtitle') };
}

export default async function DiscoverPage({ searchParams }: { searchParams: Promise<Filters> }) {
  const { q, tag, sort, access } = await searchParams;
  const filters: Filters = {
    q: q?.trim() || undefined,
    tag,
    sort: sort ?? 'popular',
    access: access === 'free' || access === 'paid' ? access : undefined,
  };

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
  const t = await getTranslations('discover');
  // Featured stays popularity-ranked so "本期精选" does not become "newest"
  // when the wall below is sorted by time or remix count.
  const feed = (await serverFetchOrNull<Page<WorkSummary>>('/v1/works', {
    query: {
      q: filters.q,
      tag: filters.tag,
      sort: 'popular',
      access: filters.access,
      limit: HERO_SLIDES,
    },
  })) ?? { items: [] };

  // The carousel shows several prominent works in full. Fetching each detail
  // separately is what gives the panel its lineage, licence and reusable
  // parameters. Public fetch keeps the hero cacheable — like/bookmark state is
  // filled in by the client session.
  const details = await Promise.all(
    feed.items.map((item) => serverFetchOrNull<WorkDetail>(`/v1/works/${item.id}`)),
  );
  const featured = details.filter((work): work is WorkDetail => work !== null);
  if (featured.length === 0) return null;

  return (
    <section>
      <SectionHeading title={t('featuredLabel')} />
      <HeroCarousel works={featured} />
    </section>
  );
}

async function InspirationSection({ filters }: { filters: Filters }) {
  const t = await getTranslations('discover');
  const filtered = Boolean(filters.q || filters.tag || filters.access);

  const [feed, tags] = await Promise.all([
    serverFetchOrNull<Page<WorkSummary>>('/v1/works', {
      query: { ...filters, limit: PAGE_SIZE },
    }),
    serverFetchOrNull<Page<Tag>>('/v1/tags', { query: { limit: 24 }, revalidate: 300 }),
  ]);
  const works = feed ?? { items: [] };
  const tagPage = tags ?? { items: [] };

  // Hero is pinned to `popular`. Only drop its leading tiles when this page
  // is the same effective query — a keyword search ignores sort on both
  // sides, and an unfiltered / tagged popular wall is the same browse.
  const wallMatchesHero = Boolean(filters.q) || filters.sort === 'popular';
  const tiles = wallMatchesHero ? works.items.slice(HERO_SLIDES) : works.items;

  return (
    <section>
      <SectionHeading title={t('inspiration')} description={t('inspirationHint')} />
      <div className="mt-4 flex flex-col gap-2">
        <TagFilter
          tags={tagPage.items}
          active={filters.tag}
          q={filters.q}
          sort={filters.sort}
          access={filters.access}
        />
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <DiscoverSort q={filters.q} tag={filters.tag} sort={filters.sort} access={filters.access} />
          <DiscoverAccess q={filters.q} tag={filters.tag} sort={filters.sort} access={filters.access} />
        </div>
      </div>
      <div className="mt-5">
        {tiles.length > 0 ? (
          <InspirationMasonry
            // Remount on a filter change: the appended pages belong to the old
            // query and there is nothing to reconcile them with.
            key={`${filters.q ?? ''}|${filters.tag ?? ''}|${filters.sort ?? ''}|${filters.access ?? ''}`}
            works={tiles}
            cursor={works.next_cursor ?? null}
            query={filters}
            pageSize={PAGE_SIZE}
          />
        ) : null}
        {works.items.length === 0 ? (
          <EmptyState
            title={filtered ? t('noResults') : t('emptyFeed')}
            description={filtered ? t('noResultsHint') : t('emptyFeedHint')}
          />
        ) : null}
      </div>
    </section>
  );
}
