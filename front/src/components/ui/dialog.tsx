'use client';

import { useCallback, useEffect, useId, useRef } from 'react';
import { createPortal } from 'react-dom';

import { cn } from '@/lib/cn';
import { loadAnime, useIsomorphicLayoutEffect, useReducedMotion } from '@/lib/motion';
import { useOverlayTransition } from '@/lib/use-overlay-transition';

const ENTER_DURATION = 220;
const EXIT_DURATION = 160;

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * Modal dialog with a focus trap, Escape to close and focus restoration.
 *
 * Built on a plain div rather than `<dialog>` because the native element's top
 * layer sits outside the themed stacking context and ignores the page's
 * backdrop tokens.
 */
export function Dialog({
  open,
  onClose,
  title,
  description,
  children,
  footer,
  size = 'md',
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: string;
  children: React.ReactNode;
  footer?: React.ReactNode;
  size?: 'sm' | 'md' | 'lg' | 'xl';
}) {
  const panelRef = useRef<HTMLDivElement>(null);
  const backdropRef = useRef<HTMLDivElement>(null);
  const restoreTo = useRef<HTMLElement | null>(null);
  const titleId = useId();
  const descriptionId = `${titleId}-description`;
  const reduced = useReducedMotion();

  const animateExit = useCallback(async (signal: AbortSignal) => {
    const { animate } = await loadAnime();
    if (signal.aborted) return;
    const backdrop = backdropRef.current;
    const panel = panelRef.current;
    await Promise.all([
      backdrop
        ? animate(backdrop, { opacity: [1, 0], duration: EXIT_DURATION, ease: 'inQuad' }).then()
        : undefined,
      panel
        ? animate(panel, {
            opacity: [1, 0],
            scale: [1, 0.96],
            translateY: [0, 8],
            duration: EXIT_DURATION,
            ease: 'inQuad',
          }).then()
        : undefined,
    ]);
  }, []);

  const render = useOverlayTransition(open, animateExit);

  // Keyed on `render` rather than `open`: `render` flips true exactly once
  // per open, in the same commit that first mounts the panel, so this is the
  // one point where the refs are guaranteed to be attached. Keying on `open`
  // instead would fire a commit early — before `useOverlayTransition` has
  // mounted anything — while the refs are still null.
  useIsomorphicLayoutEffect(() => {
    if (!render || reduced) return;
    const backdrop = backdropRef.current;
    const panel = panelRef.current;
    if (!backdrop || !panel) return;
    backdrop.style.opacity = '0';
    panel.style.opacity = '0';
    loadAnime().then(({ animate }) => {
      animate(backdrop, { opacity: [0, 1], duration: ENTER_DURATION, ease: 'outQuad' });
      animate(panel, {
        opacity: [0, 1],
        scale: [0.96, 1],
        translateY: [8, 0],
        duration: ENTER_DURATION,
        ease: 'outQuad',
      });
    });
  }, [render, reduced]);

  useEffect(() => {
    if (!open) return;

    restoreTo.current = document.activeElement as HTMLElement | null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';

    // Focus the panel itself, not its first control: reading the title before
    // landing in a text field is what makes the dialog comprehensible.
    panelRef.current?.focus();

    return () => {
      document.body.style.overflow = previousOverflow;
      restoreTo.current?.focus();
    };
  }, [open]);

  const onKeyDown = useCallback(
    (event: React.KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.stopPropagation();
        onClose();
        return;
      }
      if (event.key !== 'Tab') return;

      const focusable = Array.from(
        panelRef.current?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? [],
      ).filter((element) => element.offsetParent !== null);
      if (focusable.length === 0) return;

      const first = focusable[0]!;
      const last = focusable[focusable.length - 1]!;
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    },
    [onClose],
  );

  if (!render || typeof document === 'undefined') return null;

  // Portalled to `document.body` rather than rendered in place: a `fixed`
  // backdrop only escapes to the viewport if none of its ancestors set a
  // `transform`/`perspective`/`will-change: transform` — the discover hero
  // carousel's 3D card stack does exactly that, which would otherwise shrink
  // this dialog down to the carousel card's own clipped box.
  return createPortal(
    <div
      ref={backdropRef}
      className="fixed inset-0 z-50 flex items-end justify-center p-0 sm:items-center sm:p-6"
      style={{ background: 'var(--overlay)' }}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={description ? descriptionId : undefined}
        tabIndex={-1}
        onKeyDown={onKeyDown}
        className={cn(
          'flex max-h-[92vh] w-full flex-col overflow-hidden rounded-t-[var(--radius-lg)] border border-border',
          'bg-surface-raised shadow-raised outline-none sm:rounded-[var(--radius-lg)]',
          size === 'sm' && 'sm:max-w-md',
          size === 'md' && 'sm:max-w-lg',
          size === 'lg' && 'sm:max-w-3xl',
          size === 'xl' && 'sm:w-[60vw] sm:max-w-[60vw]',
        )}
      >
        {/* Only this pane scrolls — the footer below stays put so the
            primary actions never wander off while the reader scrolls
            through a long body. */}
        <div className="min-h-0 flex-1 overflow-y-auto p-6">
          <h2 id={titleId} className="text-xl font-semibold">
            {title}
          </h2>
          {description ? (
            <p id={descriptionId} className="mt-1.5 text-sm text-muted">
              {description}
            </p>
          ) : null}
          <div className="mt-5">{children}</div>
        </div>
        {footer ? (
          <div className="flex shrink-0 justify-end gap-3 border-t border-border px-6 py-4">
            {footer}
          </div>
        ) : null}
      </div>
    </div>,
    document.body,
  );
}
