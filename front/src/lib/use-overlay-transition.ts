'use client';

import { useRef, useState } from 'react';

import { useIsomorphicLayoutEffect, useReducedMotion } from '@/lib/motion';

/**
 * Keeps an overlay (dialog, sheet, dropdown) mounted long enough to play its
 * exit animation before it leaves the DOM.
 *
 * `open` is the caller's source of truth and can flip straight to `false` —
 * it still drives the focus trap and scroll lock elsewhere. This hook only
 * delays the *unmount* that follows: while `open` is false but `render` is
 * still true, the caller keeps its markup on screen and runs `animateExit`.
 * An `AbortController` is threaded through so a reopen mid-exit, or the
 * component unmounting outright, cannot land a stale `setRender(false)`.
 */
export function useOverlayTransition(
  open: boolean,
  animateExit: (signal: AbortSignal) => Promise<void> | void,
): boolean {
  const [render, setRender] = useState(open);
  const reduced = useReducedMotion();
  const wasOpen = useRef(open);
  const animateExitRef = useRef(animateExit);

  // Keeps the latest closure without listing `animateExit` as a dependency
  // below — that callback is typically recreated every render, and this
  // effect must only re-run when `open`/`reduced` actually change.
  useIsomorphicLayoutEffect(() => {
    animateExitRef.current = animateExit;
  });

  useIsomorphicLayoutEffect(() => {
    if (open) {
      wasOpen.current = true;
      setRender(true);
      return;
    }
    // Never opened yet (initial `open === false`) — nothing to exit from.
    if (!wasOpen.current) return;
    wasOpen.current = false;

    if (reduced) {
      setRender(false);
      return;
    }

    const controller = new AbortController();
    Promise.resolve(animateExitRef.current(controller.signal)).finally(() => {
      if (!controller.signal.aborted) setRender(false);
    });
    return () => controller.abort();
  }, [open, reduced]);

  return render;
}
