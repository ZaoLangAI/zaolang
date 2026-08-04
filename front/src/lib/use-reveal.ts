'use client';

import { useEffect, useRef } from 'react';

import { loadAnime, useReducedMotion } from '@/lib/motion';

const DEFAULT_DISTANCE = 16;
const DEFAULT_DURATION = 520;

/**
 * Ref to attach to an element that should fade and rise into place the first
 * time it enters the viewport.
 *
 * One-shot by design: the observer disconnects after firing, so scrolling an
 * element back into view does not replay the animation. Elements already in
 * the viewport at mount (e.g. the first screenful of a feed) animate almost
 * immediately, which is what gives a freshly loaded grid its staggered
 * "wave" rather than a synchronised pop.
 */
export function useRevealOnView<T extends HTMLElement>(options?: {
  distance?: number;
  duration?: number;
  delay?: number;
}) {
  const ref = useRef<T | null>(null);
  const reduced = useReducedMotion();
  const distance = options?.distance ?? DEFAULT_DISTANCE;
  const duration = options?.duration ?? DEFAULT_DURATION;
  const delay = options?.delay ?? 0;

  useEffect(() => {
    const node = ref.current;
    if (!node) return;

    if (reduced) {
      node.style.opacity = '';
      return;
    }

    node.style.opacity = '0';
    let cancelled = false;

    const observer = new IntersectionObserver(
      (entries) => {
        if (!entries.some((entry) => entry.isIntersecting)) return;
        observer.disconnect();
        loadAnime().then(({ animate }) => {
          if (cancelled) return;
          animate(node, {
            opacity: [0, 1],
            translateY: [distance, 0],
            duration,
            delay,
            ease: 'outQuad',
          });
        });
      },
      { rootMargin: '80px', threshold: 0.1 },
    );
    observer.observe(node);

    return () => {
      cancelled = true;
      observer.disconnect();
      node.style.opacity = '';
    };
  }, [reduced, distance, duration, delay]);

  return ref;
}
