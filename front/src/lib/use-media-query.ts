'use client';

import { useCallback, useSyncExternalStore } from 'react';

/**
 * The JS mirror of the `--breakpoint-*` tokens in `globals.css`.
 *
 * Duplicating the numbers is the price of asking about a breakpoint from
 * JavaScript at all; keeping the copy in one module means a change to the CSS
 * has exactly one other place to follow it.
 */
export const BREAKPOINTS = {
  xs: 480,
  sm: 760,
  md: 1024,
  lg: 1180,
  xl: 1440,
} as const;

export type Breakpoint = keyof typeof BREAKPOINTS;

/**
 * Subscribes to a media query.
 *
 * The server has no viewport, so the SSR snapshot is always `false` and the
 * markup is written so that the false branch is the correct one to hydrate
 * against. Use this for behaviour (does an open sheet still make sense?), not
 * for layout — layout belongs in CSS, where it does not have to wait for
 * hydration.
 */
export function useMediaQuery(query: string): boolean {
  const subscribe = useCallback(
    (onChange: () => void) => {
      const list = window.matchMedia(query);
      list.addEventListener('change', onChange);
      return () => list.removeEventListener('change', onChange);
    },
    [query],
  );

  return useSyncExternalStore(
    subscribe,
    () => window.matchMedia(query).matches,
    () => false,
  );
}

/** `true` once the viewport is at least as wide as the named breakpoint. */
export function useMinWidth(breakpoint: Breakpoint): boolean {
  return useMediaQuery(`(min-width: ${BREAKPOINTS[breakpoint]}px)`);
}
