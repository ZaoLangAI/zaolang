'use client';

import { useTranslations } from 'next-intl';
import { useCallback, useEffect, useId, useRef } from 'react';

import { IconClose } from '@/components/ui/icons';
import { ErrorNotice } from '@/components/ui/primitives';
import { Spinner } from '@/components/ui/spinner';
import { cn } from '@/lib/cn';
import { loadAnime, useIsomorphicLayoutEffect, useReducedMotion } from '@/lib/motion';
import { useOverlayTransition } from '@/lib/use-overlay-transition';

const ENTER_DURATION = 280;
const EXIT_DURATION = 200;
const RISE_DISTANCE = 40;

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * Bottom drawer for the narrow layouts.
 *
 * Same modal contract as `ui/dialog.tsx` — focus trap, Escape, focus
 * restoration, locked background scroll — but anchored to the bottom edge and
 * height-capped, because on a phone the reachable part of the screen is the
 * bottom half and a centred panel puts its controls under the thumb's blind
 * spot. Kept separate from `Dialog` rather than added as a variant: the two
 * differ in where they sit, how tall they are and how they are dismissed, and
 * a shared component with a `placement` prop would be branching on that in
 * every rule.
 */
export function Sheet({
  open,
  onClose,
  title,
  description,
  children,
  footer,
  loading = false,
  error,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: string;
  children: React.ReactNode;
  footer?: React.ReactNode;
  /** Blocks interaction and announces that the panel is still settling. */
  loading?: boolean;
  /** Panel-level failure, shown above the content and announced. */
  error?: string | null;
}) {
  const t = useTranslations('actions');
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
            translateY: [0, RISE_DISTANCE],
            duration: EXIT_DURATION,
            ease: 'inQuad',
          }).then()
        : undefined,
    ]);
  }, []);

  const render = useOverlayTransition(open, animateExit);

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
        translateY: [RISE_DISTANCE, 0],
        duration: ENTER_DURATION,
        ease: 'outExpo',
      });
    });
  }, [render, reduced]);

  useEffect(() => {
    if (!open) return;

    restoreTo.current = document.activeElement as HTMLElement | null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
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

  if (!render) return null;

  return (
    <div
      ref={backdropRef}
      className="fixed inset-0 z-50 flex items-end justify-center"
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
        aria-busy={loading || undefined}
        tabIndex={-1}
        onKeyDown={onKeyDown}
        className={cn(
          'flex max-h-[88dvh] w-full flex-col rounded-t-[var(--radius-lg)] border border-b-0 border-border',
          'safe-b bg-surface-raised shadow-raised outline-none sm:max-w-lg',
        )}
      >
        <header className="relative flex items-start gap-3 border-b border-border px-5 py-4">
          {/* Grab handle: the affordance people look for before they look for
              a close button. Decorative, so the button below is the real one. */}
          <span
            aria-hidden="true"
            className="absolute left-1/2 top-2 h-1 w-10 -translate-x-1/2 rounded-full bg-track"
          />
          <div className="min-w-0 flex-1">
            <h2 id={titleId} className="text-base font-semibold">
              {title}
            </h2>
            {description ? (
              <p id={descriptionId} className="mt-1 text-xs text-muted">
                {description}
              </p>
            ) : null}
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={loading}
            aria-label={t('close')}
            className={cn(
              'grid size-9 shrink-0 place-items-center rounded-[var(--radius-sm)] text-muted transition-colors',
              'hover:bg-surface-soft hover:text-text focus-visible:outline-2',
              'disabled:cursor-not-allowed disabled:opacity-50',
            )}
          >
            {loading ? <Spinner className="size-4" /> : <IconClose className="size-4" />}
          </button>
        </header>

        <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-5 py-4">
          {error ? <ErrorNotice title={error} /> : null}
          {children}
        </div>

        {footer ? (
          <div className="flex items-center gap-3 border-t border-border px-5 py-4">{footer}</div>
        ) : null}
      </div>
    </div>
  );
}
