'use client';

import { useEffect, useRef } from 'react';
import { useTranslations } from 'next-intl';

import { IconClose } from '@/components/ui/icons';
import { cn } from '@/lib/cn';

/**
 * Side panel for the row you clicked.
 *
 * A drawer rather than a route: the operator keeps the filtered list in view
 * while reading one row, which is the whole point of a triage screen. It traps
 * focus like a dialog because it covers the list on narrow screens.
 */
export function DetailDrawer({
  open,
  onClose,
  title,
  subtitle,
  children,
  footer,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  subtitle?: string;
  children: React.ReactNode;
  footer?: React.ReactNode;
}) {
  const t = useTranslations('admin');
  const panelRef = useRef<HTMLDivElement>(null);
  const restoreTo = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!open) return;
    restoreTo.current = document.activeElement as HTMLElement | null;
    panelRef.current?.focus();

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('keydown', onKeyDown);
      restoreTo.current?.focus();
    };
  }, [open, onClose]);

  if (!open) return null;

  return (
    <>
      <div
        aria-hidden="true"
        onClick={onClose}
        className="fixed inset-0 z-40 bg-overlay lg:hidden"
      />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="false"
        aria-label={title}
        tabIndex={-1}
        className={cn(
          'fixed inset-y-0 right-0 z-50 flex w-full max-w-[520px] flex-col border-l border-border bg-surface',
          'shadow-[var(--card-shadow-raised)] outline-none',
        )}
      >
        <header className="flex items-start justify-between gap-4 border-b border-border px-5 py-4">
          <div className="min-w-0">
            <h2 className="truncate text-base font-semibold">{title}</h2>
            {subtitle ? <p className="mt-0.5 truncate text-xs text-muted">{subtitle}</p> : null}
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label={t('closeDetail')}
            className="grid size-8 shrink-0 place-items-center rounded-[var(--radius-sm)] text-muted hover:bg-surface-soft hover:text-text"
          >
            <IconClose className="size-4" />
          </button>
        </header>

        <div className="flex-1 overflow-y-auto px-5 py-4">{children}</div>

        {footer ? (
          <footer className="flex flex-wrap justify-end gap-2 border-t border-border px-5 py-4">
            {footer}
          </footer>
        ) : null}
      </div>
    </>
  );
}

/** Label/value rows, the drawer's default body layout. */
export function DetailList({ items }: { items: Array<{ label: string; value: React.ReactNode }> }) {
  return (
    <dl className="flex flex-col divide-y divide-border text-sm">
      {items.map((item) => (
        <div key={item.label} className="flex gap-4 py-2.5">
          <dt className="w-32 shrink-0 text-xs text-muted">{item.label}</dt>
          <dd className="min-w-0 flex-1 break-words">{item.value}</dd>
        </div>
      ))}
    </dl>
  );
}
