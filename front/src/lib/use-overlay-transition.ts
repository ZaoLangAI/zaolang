'use client';

import { useRef, useState } from 'react';

import { useIsomorphicLayoutEffect, useReducedMotion } from '@/lib/motion';

/**
 * Longest real exit animation among this hook's callers (`sheet.tsx`'s
 * 200ms) plus generous headroom for the `loadAnime()` chunk fetch. Past this,
 * `animateExit`'s promise is treated as hung rather than merely slow.
 */
const EXIT_FALLBACK_TIMEOUT_MS = 1500;

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
 *
 * A fallback timer backstops `animateExit`'s promise the same way
 * `beginLocaleTransition`'s does for the locale fade: an animation whose
 * `.then()` never settles (an animejs/WAAPI animation starved by an
 * unrelated `document.startViewTransition()` elsewhere on the page has been
 * observed to do exactly this) must not leave the overlay's backdrop
 * covering the page — pointer-events already passed through by this point,
 * so it would just sit there fully opaque and inert forever.
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
    let settled = false;
    const unmount = () => {
      if (settled) return;
      settled = true;
      clearTimeout(fallback);
      if (!controller.signal.aborted) setRender(false);
    };
    const fallback = setTimeout(unmount, EXIT_FALLBACK_TIMEOUT_MS);
    Promise.resolve(animateExitRef.current(controller.signal)).finally(unmount);
    return () => {
      controller.abort();
      clearTimeout(fallback);
    };
  }, [open, reduced]);

  return render;
}
