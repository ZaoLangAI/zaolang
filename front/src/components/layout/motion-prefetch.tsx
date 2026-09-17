'use client';

import { useEffect } from 'react';

import { loadAnime, useReducedMotion } from '@/lib/motion';

/**
 * Warms the animejs chunk on idle so the first Dialog/Sheet open is not
 * waiting on a network parse. Skipped when motion is reduced.
 */
export function MotionPrefetch() {
  const reduced = useReducedMotion();

  useEffect(() => {
    if (reduced) return;

    let idleId: number | undefined;
    let timeoutId: number | undefined;
    const warm = () => {
      void loadAnime();
    };

    if (typeof window.requestIdleCallback === 'function') {
      idleId = window.requestIdleCallback(warm, { timeout: 2500 });
    } else {
      timeoutId = window.setTimeout(warm, 1400);
    }

    return () => {
      if (idleId !== undefined) window.cancelIdleCallback(idleId);
      if (timeoutId !== undefined) window.clearTimeout(timeoutId);
    };
  }, [reduced]);

  return null;
}
