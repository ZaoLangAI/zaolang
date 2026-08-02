'use client';

import dynamic from 'next/dynamic';
import { useEffect, useState } from 'react';

const CommandPalette = dynamic(
  () => import('@/components/command/command-palette').then((mod) => mod.CommandPalette),
  { ssr: false },
);

/**
 * Defers the Cmd+K palette chunk until idle (or the first shortcut) so the
 * site shell does not pay for search UI on every navigation.
 */
export function CommandPaletteHost() {
  const [ready, setReady] = useState(false);
  const [openSignal, setOpenSignal] = useState(0);

  useEffect(() => {
    if (ready) return;

    const onKeyDown = (event: KeyboardEvent) => {
      const isPaletteShortcut =
        (event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k';
      const target = event.target as HTMLElement | null;
      const typing =
        target?.tagName === 'INPUT' ||
        target?.tagName === 'TEXTAREA' ||
        target?.isContentEditable === true;

      if (isPaletteShortcut || (event.key === '/' && !typing)) {
        event.preventDefault();
        setReady(true);
        setOpenSignal((value) => value + 1);
      }
    };

    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [ready]);

  useEffect(() => {
    if (ready) return;

    let idleId: number | undefined;
    let timeoutId: number | undefined;
    const enable = () => setReady(true);

    if (typeof window.requestIdleCallback === 'function') {
      idleId = window.requestIdleCallback(enable, { timeout: 2000 });
    } else {
      timeoutId = window.setTimeout(enable, 1200);
    }

    return () => {
      if (idleId !== undefined) window.cancelIdleCallback(idleId);
      if (timeoutId !== undefined) window.clearTimeout(timeoutId);
    };
  }, [ready]);

  if (!ready) return null;
  return <CommandPalette openSignal={openSignal} />;
}
