'use client';

import { useEffect, useLayoutEffect } from 'react';
import type * as Anime from 'animejs';

import { useTheme } from '@/components/theme/theme-provider';
import { useMediaQuery } from '@/lib/use-media-query';

/**
 * `useLayoutEffect` on the client, `useEffect` on the server.
 *
 * These components render during SSR too (Next.js still produces HTML for
 * `'use client'` components), and plain `useLayoutEffect` warns there because
 * it has no server-side effect to encode. The animation timing this is used
 * for — setting a pre-animation style before the browser's first paint —
 * only matters once there is a browser at all.
 */
export const useIsomorphicLayoutEffect =
  typeof window === 'undefined' ? useEffect : useLayoutEffect;

/**
 * Lazy, memoised `animejs` loader.
 *
 * Imported dynamically rather than at module scope: animejs never has a
 * reason to run during SSR or the RSC build graph, and pages that never
 * trigger an animation should not pay for it in their first-load bundle.
 * The promise is cached so concurrent callers share one network/parse cost.
 */
let animePromise: Promise<typeof Anime> | null = null;

export function loadAnime(): Promise<typeof Anime> {
  animePromise ??= import('animejs');
  return animePromise;
}

/**
 * Whether motion should be suppressed, from either source that can demand it.
 *
 * The app's own "reduce motion" toggle (`useTheme`) and the OS-level
 * `prefers-reduced-motion` media query are independent — a user can flip one
 * without the other — so both are checked and either is enough to disable
 * JS-driven animation. This only covers `animate()` calls made through this
 * module; the CSS side of the same invariant lives in `globals.css`.
 */
export function useReducedMotion(): boolean {
  const { reduceMotion } = useTheme();
  const osReduced = useMediaQuery('(prefers-reduced-motion: reduce)');
  return reduceMotion || osReduced;
}
