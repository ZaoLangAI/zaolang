'use client';

import { useTranslations } from 'next-intl';
import { useEffect, useMemo, useRef, useState } from 'react';

import { useSession } from '@/components/auth/session-provider';
import { Poster } from '@/components/media/poster';
import { IconButton } from '@/components/ui/button';
import { IconChevronLeft, IconChevronRight } from '@/components/ui/icons';
import { Skeleton } from '@/components/ui/primitives';
import { WorkInfoPanel } from '@/components/work/work-info-panel';
import { WorkStage } from '@/components/work/work-stage';
import { api } from '@/lib/api/client';
import type { WorkDetail, WorkSummary } from '@/lib/api/types';
import { cn, controlPress } from '@/lib/cn';
import { useReducedMotion } from '@/lib/motion';

/** Long enough to read a card, short enough that the rotation still feels alive. */
const AUTOPLAY_INTERVAL_MS = 6000;

/** Active card plus one neighbour on each side — a three-up coverflow, not a full ring. */
const OFFSET_RANGE = 1;

const SIDE_ROTATE_DEG = 38;
const SIDE_TRANSLATE_X_PCT = 62;
const SIDE_TRANSLATE_Z_PX = 180;
const SIDE_SCALE = 0.84;
const SIDE_OPACITY = 0.45;

/**
 * One height, shared by the video pane and the info pane of every card, so
 * the two halves always line up exactly instead of the video trailing off
 * wherever its own aspect ratio happens to land.
 */
const CARD_HEIGHT = 'h-[300px] sm:h-[360px] md:h-[420px] lg:h-[480px]';

function signedOffset(itemIndex: number, activeIndex: number, count: number): number {
  let diff = itemIndex - activeIndex;
  const half = count / 2;
  if (diff > half) diff -= count;
  else if (diff < -half) diff += count;
  return diff;
}

function slideTransform(offset: number): string {
  if (offset === 0) return 'translate3d(0, 0, 0) rotateY(0deg) scale(1)';
  const sign = offset > 0 ? 1 : -1;
  return `translate3d(${sign * SIDE_TRANSLATE_X_PCT}%, 0, ${-SIDE_TRANSLATE_Z_PX}px) rotateY(${-sign * SIDE_ROTATE_DEG}deg) scale(${SIDE_SCALE})`;
}

function neighborIds(slides: WorkSummary[], activeIndex: number): string[] {
  const count = slides.length;
  if (count === 0) return [];
  const ids: string[] = [];
  for (let workIndex = 0; workIndex < count; workIndex += 1) {
    if (Math.abs(signedOffset(workIndex, activeIndex, count)) <= OFFSET_RANGE) {
      ids.push(slides[workIndex]!.id);
    }
  }
  return ids;
}

/**
 * The discover hero: a 3D "coverflow" carousel of currently popular works.
 *
 * The RSC only seeds the first slide's detail. Neighbours load as they enter
 * the three-up window; only the active card mounts a `WorkStage` so at most
 * one video player is live.
 */
export function HeroCarousel({
  slides,
  initialDetails,
}: {
  slides: WorkSummary[];
  initialDetails: Record<string, WorkDetail>;
}) {
  const t = useTranslations('discover');
  const reducedMotion = useReducedMotion();
  const { status } = useSession();
  const [index, setIndex] = useState(0);
  const [paused, setPaused] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const [details, setDetails] = useState<Record<string, WorkDetail>>(initialDetails);

  const [bookmarkOverrides, setBookmarkOverrides] = useState<Record<string, boolean>>({});

  const count = slides.length;
  const slidesKey = slides.map((slide) => slide.id).join('|');
  const [trackedSlidesKey, setTrackedSlidesKey] = useState(slidesKey);
  if (trackedSlidesKey !== slidesKey) {
    setTrackedSlidesKey(slidesKey);
    setIndex(0);
    setDetails(initialDetails);
  }
  // Which works have been fetched for the current slide set. Reset inside the
  // fetch effect, not in the render-time block above: refs can't be written
  // during render (`react-hooks/refs`).
  const requestedRef = useRef({ slidesKey, ids: new Set(Object.keys(initialDetails)) });

  const mountedIds = useMemo(() => neighborIds(slides, index), [slides, index]);
  const mountedKey = mountedIds.join('|');

  useEffect(() => {
    if (requestedRef.current.slidesKey !== slidesKey) {
      requestedRef.current = { slidesKey, ids: new Set(Object.keys(initialDetails)) };
    }
    const requested = requestedRef.current.ids;
    const missing = mountedIds.filter((id) => !requested.has(id));
    if (missing.length === 0) return;
    for (const id of missing) requested.add(id);
    let cancelled = false;
    void Promise.all(
      missing.map(async (workId) => {
        try {
          return await api.get<WorkDetail>(`/v1/works/${workId}`);
        } catch {
          return null;
        }
      }),
    ).then((results) => {
      if (cancelled) return;
      setDetails((current) => {
        const next = { ...current };
        for (const work of results) {
          if (work) next[work.id] = work;
        }
        return next;
      });
    });
    return () => {
      cancelled = true;
    };
  }, [mountedIds, slidesKey, initialDetails]);

  useEffect(() => {
    if (status !== 'authenticated' || mountedKey === '') return;
    let cancelled = false;
    void Promise.all(
      mountedKey.split('|').map(async (workId) => {
        try {
          const detail = await api.get<WorkDetail>(`/v1/works/${workId}`);
          return [workId, detail.viewer_bookmarked] as const;
        } catch {
          return null;
        }
      }),
    ).then((results) => {
      if (cancelled) return;
      setBookmarkOverrides((current) => {
        const next = { ...current };
        for (const result of results) {
          if (result) next[result[0]] = result[1];
        }
        return next;
      });
    });
    return () => {
      cancelled = true;
    };
  }, [status, mountedKey]);

  useEffect(() => {
    if (count <= 1 || paused || reducedMotion) return;
    const timer = window.setInterval(() => {
      setIndex((current) => (current + 1) % count);
    }, AUTOPLAY_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [count, paused, reducedMotion]);

  const goTo = (next: number) => setIndex(((next % count) + count) % count);

  return (
    <div
      ref={containerRef}
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
      onFocus={() => setPaused(true)}
      onBlur={(event) => {
        if (!containerRef.current?.contains(event.relatedTarget as Node)) setPaused(false);
      }}
    >
      <div className={cn('relative overflow-hidden', CARD_HEIGHT)}>
        <div
          role="group"
          aria-label={t('featuredCarousel')}
          className="relative size-full perspective-distant transform-3d"
        >
          {slides.map((slide, workIndex) => {
            const offset = signedOffset(workIndex, index, count);
            if (Math.abs(offset) > OFFSET_RANGE) return null;
            const active = offset === 0;
            const detail = details[slide.id];
            const bookmarkOverride = bookmarkOverrides[slide.id];
            const cardWork =
              detail === undefined
                ? undefined
                : bookmarkOverride === undefined
                  ? detail
                  : { ...detail, viewer_bookmarked: bookmarkOverride };

            return (
              <div
                key={slide.id}
                inert={active ? undefined : true}
                aria-hidden={active ? undefined : true}
                className={cn(
                  'absolute inset-0 will-change-transform transition-[transform,opacity] ease-out',
                  reducedMotion ? 'duration-0' : 'duration-700',
                )}
                style={{
                  transform: slideTransform(offset),
                  opacity: active ? 1 : SIDE_OPACITY,
                  zIndex: active ? 3 : 1,
                }}
              >
                <div className="flex h-full gap-3 sm:gap-5">
                  <div className="h-full flex-[3] overflow-hidden rounded-[var(--radius-lg)]">
                    {active && cardWork ? (
                      <WorkStage work={cardWork} lazyMedia fill className="h-full" />
                    ) : (
                      <Poster
                        src={slide.cover_url}
                        alt={slide.title}
                        aspect="fill"
                        className="h-full rounded-none border-0"
                        mediaType={slide.media_type}
                        priority={active}
                      />
                    )}
                  </div>
                  <aside
                    tabIndex={0}
                    className="h-full min-w-0 flex-[2] overflow-y-auto rounded-[var(--radius-lg)] border border-border bg-surface p-4 lg:p-6"
                  >
                    {cardWork ? (
                      <WorkInfoPanel
                        work={cardWork}
                        compact
                        onBookmarkedChange={(next) =>
                          setBookmarkOverrides((current) => ({ ...current, [slide.id]: next }))
                        }
                      />
                    ) : (
                      <div className="flex flex-col gap-3" aria-busy="true">
                        <Skeleton className="h-3 w-20" />
                        <Skeleton className="h-7 w-[80%]" />
                        <Skeleton className="h-4 w-full" />
                        <Skeleton className="h-4 w-[66%]" />
                      </div>
                    )}
                  </aside>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {count > 1 ? (
        <div className="mt-4 flex items-center justify-center gap-4">
          <IconButton
            variant="secondary"
            size="sm"
            label={t('previousFeatured')}
            onClick={() => goTo(index - 1)}
            className="rounded-full"
          >
            <IconChevronLeft className="size-5" />
          </IconButton>

          <div className="flex gap-2">
            {slides.map((slide, tileIndex) => (
              <button
                key={slide.id}
                type="button"
                aria-label={t('goToSlide', { index: tileIndex + 1 })}
                aria-current={tileIndex === index ? 'true' : undefined}
                onClick={() => goTo(tileIndex)}
                className={cn(
                  'h-2 rounded-full',
                  controlPress,
                  tileIndex === index ? 'w-6 bg-primary' : 'w-2 bg-border hover:bg-muted/50',
                )}
              />
            ))}
          </div>

          <IconButton
            variant="secondary"
            size="sm"
            label={t('nextFeatured')}
            onClick={() => goTo(index + 1)}
            className="rounded-full"
          >
            <IconChevronRight className="size-5" />
          </IconButton>
        </div>
      ) : null}
    </div>
  );
}
