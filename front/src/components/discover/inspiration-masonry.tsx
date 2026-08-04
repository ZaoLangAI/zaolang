'use client';

import { useTranslations } from 'next-intl';
import { useCallback, useEffect, useRef, useState } from 'react';

import { InspirationCard } from '@/components/discover/inspiration-card';
import { InspirationDialog } from '@/components/discover/inspiration-dialog';
import {
  INSPIRATION_COLUMNS,
  INSPIRATION_TILE,
  InspirationTileSkeleton,
} from '@/components/discover/inspiration-skeleton';
import { Button } from '@/components/ui/button';
import { api } from '@/lib/api/client';
import type { Page, WorkSummary } from '@/lib/api/types';

/** Tiles shown as placeholders while the next page is in flight. */
const PENDING_TILES = 5;

/** Leading tiles of the first page that skip lazy image loading. */
const PRIORITY_TILES = 5;

/** Start fetching this far before the wall's bottom edge enters the viewport. */
const PREFETCH_MARGIN = '600px';

type Status = 'idle' | 'loading' | 'failed';

interface FeedQuery {
  q?: string;
  tag?: string;
  sort?: string;
}

/**
 * The inspiration wall: a masonry of covers, paged by scroll.
 *
 * CSS multi-column rather than a measured JS layout: the column count is a
 * media query, the browser balances the tiles, and there is no resize listener
 * to keep in sync. Reading order goes down a column instead of across a row,
 * which is what a wall of unrelated works wants anyway.
 *
 * Each loaded page gets its own column block. A single shared block would flow
 * more evenly, but the browser rebalances a multi-column container on every
 * append — tiles the reader has already passed would jump to another column
 * mid-scroll. Per-page blocks keep everything above the newest page still.
 */
export function InspirationMasonry({
  works,
  cursor: initialCursor,
  query,
  pageSize,
}: {
  works: WorkSummary[];
  /** `null` once the feed is exhausted, or when the query cannot be resumed. */
  cursor: string | null;
  query: FeedQuery;
  pageSize: number;
}) {
  const t = useTranslations('discover');
  const [preview, setPreview] = useState<WorkSummary | null>(null);
  const [pages, setPages] = useState<WorkSummary[][]>([works]);
  const [cursor, setCursor] = useState(initialCursor);
  const [status, setStatus] = useState<Status>('idle');

  const sentinelRef = useRef<HTMLDivElement | null>(null);
  const inFlightRef = useRef(false);
  // The observer and the button can both fire for the same page; ids already on
  // the wall are dropped so a re-published work cannot show up twice.
  const seenRef = useRef(new Set(works.map((work) => work.id)));

  const loadMore = useCallback(async () => {
    if (!cursor || inFlightRef.current) return;
    inFlightRef.current = true;
    setStatus('loading');
    try {
      const next = await api.get<Page<WorkSummary>>('/v1/works', {
        query: { ...query, cursor, limit: pageSize },
      });
      const fresh = next.items.filter((work) => !seenRef.current.has(work.id));
      for (const work of fresh) seenRef.current.add(work.id);
      if (fresh.length > 0) setPages((current) => [...current, fresh]);
      setCursor(next.next_cursor ?? null);
      setStatus('idle');
    } catch {
      setStatus('failed');
    } finally {
      inFlightRef.current = false;
    }
  }, [cursor, pageSize, query]);

  useEffect(() => {
    const node = sentinelRef.current;
    // After a failure the sentinel is detached: an observer that keeps firing
    // would hammer an endpoint that just refused us. The button takes over.
    if (!node || !cursor || status === 'failed') return;

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) void loadMore();
      },
      { rootMargin: PREFETCH_MARGIN },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [cursor, loadMore, status]);

  return (
    <>
      {pages.map((page, pageIndex) => (
        <ul
          key={page[0]?.id ?? pageIndex}
          aria-label={pageIndex === 0 ? t('inspiration') : undefined}
          className={pageIndex === 0 ? INSPIRATION_COLUMNS : `mt-4 ${INSPIRATION_COLUMNS}`}
        >
          {page.map((work, index) => (
            <li key={work.id} className={INSPIRATION_TILE}>
              <InspirationCard
                work={work}
                onOpen={setPreview}
                priority={pageIndex === 0 && index < PRIORITY_TILES}
              />
            </li>
          ))}
        </ul>
      ))}

      {status === 'loading' ? (
        <ul aria-busy="true" className={`mt-4 ${INSPIRATION_COLUMNS}`}>
          {Array.from({ length: PENDING_TILES }, (_, index) => (
            <li key={index} className={INSPIRATION_TILE}>
              <InspirationTileSkeleton index={index} />
            </li>
          ))}
        </ul>
      ) : null}

      <div ref={sentinelRef} className="mt-4 flex justify-center">
        {status === 'failed' ? (
          <Button variant="secondary" size="sm" onClick={() => void loadMore()}>
            {t('loadMoreFailed')}
          </Button>
        ) : cursor === null ? (
          <p className="text-xs text-muted">{t('feedEnd')}</p>
        ) : (
          // A real button, not just the sentinel: scroll-driven loading leaves
          // keyboard and reduced-motion users with no way to reach page two.
          <Button
            variant="ghost"
            size="sm"
            loading={status === 'loading'}
            onClick={() => void loadMore()}
          >
            {status === 'loading' ? t('loadingMore') : t('loadMore')}
          </Button>
        )}
      </div>

      <InspirationDialog work={preview} open={preview !== null} onClose={() => setPreview(null)} />
    </>
  );
}
