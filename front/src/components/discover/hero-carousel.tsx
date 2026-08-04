'use client';

import { useTranslations } from 'next-intl';
import { useEffect, useRef, useState } from 'react';

import { useSession } from '@/components/auth/session-provider';
import { WorkInfoPanel } from '@/components/work/work-info-panel';
import { WorkStage } from '@/components/work/work-stage';
import { IconChevronLeft, IconChevronRight } from '@/components/ui/icons';
import { api } from '@/lib/api/client';
import type { WorkDetail } from '@/lib/api/types';
import { cn } from '@/lib/cn';
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

/**
 * The discover hero: a 3D "coverflow" carousel of currently popular works.
 *
 * Video and info pane share one transform and rotate as a single rigid card
 * — that's what reads as a stack of ad cards turning in space, rather than
 * two unrelated slideshows that happen to share a page. Only the active card
 * and its immediate neighbours are mounted, so at most three video players
 * ever exist in the DOM at once.
 */
export function HeroCarousel({ works }: { works: WorkDetail[] }) {
  const t = useTranslations('discover');
  const reducedMotion = useReducedMotion();
  const { status } = useSession();
  const [index, setIndex] = useState(0);
  const [paused, setPaused] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  // Only the active card and its immediate neighbours stay mounted (see
  // below), so a card's own `bookmarked` state resets to `work.viewer_bookmarked`
  // every time it rotates back into range. Tracking the latest toggle here,
  // outside the card's lifetime, is what makes a bookmark stick through a
  // full rotation instead of reverting the moment the card is remounted.
  const [bookmarkOverrides, setBookmarkOverrides] = useState<Record<string, boolean>>({});

  const count = works.length;

  // A filter change swaps in a different set of works; adjusted during render
  // (rather than in an effect) so the stale index never paints, even for a
  // single frame. Keyed on identity, not length, so a same-sized reshuffle
  // still resets to the first slide.
  const worksKey = works.map((work) => work.id).join('|');
  const [trackedWorksKey, setTrackedWorksKey] = useState(worksKey);
  if (trackedWorksKey !== worksKey) {
    setTrackedWorksKey(worksKey);
    setIndex(0);
  }

  // The hero is fetched from the server *without* the viewer's session, so it
  // stays cacheable — `work.viewer_bookmarked` on every card is really "was
  // this bookmarked by nobody in particular". Once the session resolves in
  // the browser, re-check each card against the signed-in viewer so a
  // bookmark made in an earlier visit still shows up after a reload, not
  // just across an in-page rotation.
  useEffect(() => {
    if (status !== 'authenticated' || worksKey === '') return;
    let cancelled = false;
    void Promise.all(
      worksKey.split('|').map(async (workId) => {
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
  }, [status, worksKey]);

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
      {/* The clip and the 3D context are deliberately two elements, not one:
          Safari drops the perspective transform to a blank box when
          `overflow-hidden` and `perspective`/`transform-3d` land on the same
          element, so the outer div only clips and the inner one only tilts. */}
      <div className={cn('relative overflow-hidden', CARD_HEIGHT)}>
        <div
          role="group"
          aria-label={t('featuredCarousel')}
          className="relative size-full perspective-distant transform-3d"
        >
          {works.map((work, workIndex) => {
            const offset = signedOffset(workIndex, index, count);
            if (Math.abs(offset) > OFFSET_RANGE) return null;
            const active = offset === 0;
            const bookmarkOverride = bookmarkOverrides[work.id];
            const cardWork =
              bookmarkOverride === undefined
                ? work
                : { ...work, viewer_bookmarked: bookmarkOverride };

            return (
              <div
                key={work.id}
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
                    <WorkStage work={cardWork} lazyMedia fill className="h-full" />
                  </div>
                  <aside className="h-full min-w-0 flex-[2] overflow-y-auto rounded-[var(--radius-lg)] border border-border bg-surface p-4 lg:p-6">
                    <WorkInfoPanel
                      work={cardWork}
                      compact
                      onBookmarkedChange={(next) =>
                        setBookmarkOverrides((current) => ({ ...current, [work.id]: next }))
                      }
                    />
                  </aside>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {count > 1 ? (
        <div className="mt-4 flex items-center justify-center gap-4">
          <button
            type="button"
            aria-label={t('previousFeatured')}
            onClick={() => goTo(index - 1)}
            className="inline-flex size-9 items-center justify-center rounded-full border border-border text-muted transition-colors hover:border-primary/40 hover:text-text focus-visible:outline-2"
          >
            <IconChevronLeft className="size-5" />
          </button>

          <div className="flex gap-2">
            {works.map((work, tileIndex) => (
              <button
                key={work.id}
                type="button"
                aria-label={t('goToSlide', { index: tileIndex + 1 })}
                aria-current={tileIndex === index ? 'true' : undefined}
                onClick={() => goTo(tileIndex)}
                className={cn(
                  'h-2 rounded-full transition-all',
                  tileIndex === index ? 'w-6 bg-primary' : 'w-2 bg-border hover:bg-muted/50',
                )}
              />
            ))}
          </div>

          <button
            type="button"
            aria-label={t('nextFeatured')}
            onClick={() => goTo(index + 1)}
            className="inline-flex size-9 items-center justify-center rounded-full border border-border text-muted transition-colors hover:border-primary/40 hover:text-text focus-visible:outline-2"
          >
            <IconChevronRight className="size-5" />
          </button>
        </div>
      ) : null}
    </div>
  );
}
