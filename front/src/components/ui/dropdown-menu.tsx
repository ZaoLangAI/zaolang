'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

import { IconChevronDown } from '@/components/ui/icons';
import { cn } from '@/lib/cn';
import { loadAnime, useIsomorphicLayoutEffect, useReducedMotion } from '@/lib/motion';
import { useOverlayTransition } from '@/lib/use-overlay-transition';

const ENTER_DURATION = 140;
const EXIT_DURATION = 100;

/**
 * Popover menu with a single-choice item set.
 *
 * Hand-rolled rather than pulled from a component library: the top bar menus
 * have to consume the same theme tokens as the rest of the page, and a library
 * would bring its own colours. Closing on outside pointer-down and on Escape
 * lives here so every menu behaves the same way.
 */
export function DropdownMenu({
  triggerIcon,
  triggerLabel,
  ariaLabel,
  align = 'end',
  width = 'w-52',
  children,
}: {
  triggerIcon: React.ReactNode;
  /** Shown next to the icon from `sm` up; hidden on narrow viewports. */
  triggerLabel?: string;
  ariaLabel: string;
  align?: 'start' | 'end';
  width?: string;
  children: React.ReactNode | ((close: () => void) => React.ReactNode);
}) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const reduced = useReducedMotion();

  const animateExit = useCallback(async (signal: AbortSignal) => {
    const { animate } = await loadAnime();
    if (signal.aborted || !panelRef.current) return;
    await animate(panelRef.current, {
      opacity: [1, 0],
      scale: [1, 0.95],
      duration: EXIT_DURATION,
      ease: 'inQuad',
    }).then();
  }, []);

  const render = useOverlayTransition(open, animateExit);

  useIsomorphicLayoutEffect(() => {
    if (!render || reduced) return;
    const panel = panelRef.current;
    if (!panel) return;
    panel.style.opacity = '0';
    loadAnime().then(({ animate }) => {
      animate(panel, {
        opacity: [0, 1],
        scale: [0.95, 1],
        duration: ENTER_DURATION,
        ease: 'outQuad',
      });
    });
  }, [render, reduced]);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false);
    };
    document.addEventListener('pointerdown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('pointerdown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [open]);

  const close = () => setOpen(false);

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={ariaLabel}
        onClick={() => setOpen((value) => !value)}
        className="inline-flex h-9 shrink-0 items-center gap-1.5 rounded-[var(--radius-sm)] border border-border bg-surface-soft px-2.5 text-xs font-medium text-text transition-colors hover:border-muted/40 focus-visible:outline-2"
      >
        <span className="shrink-0 text-muted">{triggerIcon}</span>
        {triggerLabel ? (
          <span className="hidden whitespace-nowrap sm:inline">{triggerLabel}</span>
        ) : null}
        <IconChevronDown className="size-3.5 shrink-0 text-muted" />
      </button>

      {render ? (
        <div
          ref={panelRef}
          role="menu"
          aria-label={ariaLabel}
          style={{ transformOrigin: align === 'end' ? 'top right' : 'top left' }}
          className={cn(
            'absolute z-40 mt-2 rounded-[var(--radius-md)] border border-border bg-surface-raised p-2 shadow-raised',
            width,
            align === 'end' ? 'right-0' : 'left-0',
          )}
        >
          {typeof children === 'function' ? children(close) : children}
        </div>
      ) : null}
    </div>
  );
}

export function DropdownMenuGroup({
  label,
  children,
}: {
  label?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="mb-2 last:mb-0">
      {label ? (
        <p className="px-1 pb-1 text-[11px] font-semibold uppercase tracking-wider text-muted">
          {label}
        </p>
      ) : null}
      <div className="flex flex-col">{children}</div>
    </div>
  );
}

export function DropdownMenuRadioItem({
  selected,
  onSelect,
  icon,
  children,
}: {
  selected: boolean;
  onSelect: () => void;
  icon?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      role="menuitemradio"
      aria-checked={selected}
      onClick={onSelect}
      className={cn(
        'flex h-9 items-center gap-2 rounded-[var(--radius-sm)] px-2 text-left text-sm transition-colors focus-visible:outline-2',
        selected ? 'bg-primary/12 text-primary' : 'text-text hover:bg-surface-soft',
      )}
    >
      {icon}
      {children}
    </button>
  );
}

export function DropdownMenuFooter({ children }: { children: React.ReactNode }) {
  return (
    <p className="mt-1 flex items-center gap-1.5 border-t border-border px-1 pt-2 text-[11px] text-muted">
      {children}
    </p>
  );
}
