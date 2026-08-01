'use client';

import { useTranslations } from 'next-intl';
import { useCallback, useEffect, useRef, useState } from 'react';

import { WorkCard } from '@/components/work/work-card';
import { IconChevronLeft, IconChevronRight } from '@/components/ui/icons';
import type { WorkSummary } from '@/lib/api/types';
import { cn } from '@/lib/cn';

/**
 * Horizontally scrolling rail of work cards.
 *
 * Native scroll rather than a transform carousel: it keeps the swipe gesture,
 * the scrollbar and keyboard scrolling for free, and it cannot desynchronise
 * from the DOM the way an index-driven carousel can.
 */
export function WorkRail({ works }: { works: WorkSummary[] }) {
  const t = useTranslations('a11y');
  const trackRef = useRef<HTMLUListElement>(null);
  const [page, setPage] = useState(0);
  const [pages, setPages] = useState(1);

  const measure = useCallback(() => {
    const track = trackRef.current;
    if (!track) return;
    const total = Math.max(1, Math.ceil(track.scrollWidth / track.clientWidth));
    setPages(total);
    setPage(Math.round(track.scrollLeft / track.clientWidth));
  }, []);

  useEffect(() => {
    const track = trackRef.current;
    if (!track) return;
    measure();
    track.addEventListener('scroll', measure, { passive: true });
    const observer = new ResizeObserver(measure);
    observer.observe(track);
    return () => {
      track.removeEventListener('scroll', measure);
      observer.disconnect();
    };
  }, [measure]);

  const scrollByPage = (direction: -1 | 1) => {
    const track = trackRef.current;
    if (!track) return;
    track.scrollBy({ left: direction * track.clientWidth, behavior: 'smooth' });
  };

  const goToPage = (index: number) => {
    const track = trackRef.current;
    if (!track) return;
    track.scrollTo({ left: index * track.clientWidth, behavior: 'smooth' });
  };

  return (
    <div className="relative">
      <ul
        ref={trackRef}
        className="no-scrollbar -mx-1 flex snap-x snap-mandatory gap-4 overflow-x-auto px-1 pb-1"
      >
        {works.map((work, index) => (
          <li
            key={work.id}
            className="w-[68%] shrink-0 snap-start sm:w-[42%] md:w-[31%] lg:w-[19%]"
          >
            <WorkCard work={work} priority={index < 3} />
          </li>
        ))}
      </ul>

      {pages > 1 ? (
        <>
          <button
            type="button"
            aria-label={t('previousSlide')}
            onClick={() => scrollByPage(-1)}
            disabled={page === 0}
            className="absolute -left-3 top-[28%] hidden size-9 place-items-center rounded-full border border-border bg-surface-raised text-muted shadow-card hover:text-text disabled:opacity-40 md:grid"
          >
            <IconChevronLeft className="size-4" />
          </button>
          <button
            type="button"
            aria-label={t('nextSlide')}
            onClick={() => scrollByPage(1)}
            disabled={page >= pages - 1}
            className="absolute -right-3 top-[28%] hidden size-9 place-items-center rounded-full border border-border bg-surface-raised text-muted shadow-card hover:text-text disabled:opacity-40 md:grid"
          >
            <IconChevronRight className="size-4" />
          </button>

          <div className="mt-4 flex justify-center gap-2">
            {Array.from({ length: pages }, (_, index) => (
              <button
                key={index}
                type="button"
                aria-label={t('goToSlide', { index: index + 1 })}
                aria-current={index === page ? 'true' : undefined}
                onClick={() => goToPage(index)}
                className={cn(
                  'size-2 rounded-full transition-colors',
                  index === page ? 'bg-primary' : 'bg-track',
                )}
              />
            ))}
          </div>
        </>
      ) : null}
    </div>
  );
}
