'use client';

import { useTranslations } from 'next-intl';
import { useEffect, useRef } from 'react';

export interface ContextMenuState {
  x: number;
  y: number;
  /** Null when the right-click landed on empty canvas rather than a card. */
  nodeId: string | null;
  /** Whether anything is selected when the menu opens.
   *
   * The menu keys its actions off this rather than off `nodeId`: React Flow
   * positions cards on a transformed pane, so a right-click aimed squarely at
   * a card frequently resolves to the pane underneath it. Offering the
   * selection's actions whenever there *is* a selection matches what the user
   * meant, and is what other canvas tools do. */
  hasSelection: boolean;
}

interface Action {
  key: string;
  label: string;
  run: () => void;
  disabled?: boolean;
  danger?: boolean;
}

/**
 * Right-click menu for the canvas.
 *
 * Positioned in viewport coordinates and rendered as a plain absolutely
 * positioned list rather than through a popover library — it has to follow the
 * pointer exactly, and the repo has no menu primitive that takes a raw point.
 */
export function CanvasContextMenu({
  state,
  onClose,
  onAddNote,
  onDuplicate,
  onCopy,
  onPaste,
  onDelete,
  canPaste,
}: {
  state: ContextMenuState | null;
  onClose: () => void;
  onAddNote: (at: { x: number; y: number }) => void;
  onDuplicate: () => void;
  onCopy: () => void;
  onPaste: (at: { x: number; y: number }) => void;
  onDelete: () => void;
  canPaste: boolean;
}) {
  const t = useTranslations('canvas');
  const ref = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!state) return undefined;
    const dismiss = (event: MouseEvent) => {
      if (ref.current?.contains(event.target as Node)) return;
      onClose();
    };
    const onEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    // `mousedown`, not `click`: a click listener fires for the same gesture
    // that opened the menu on some platforms and closes it immediately.
    window.addEventListener('mousedown', dismiss);
    window.addEventListener('keydown', onEscape);
    return () => {
      window.removeEventListener('mousedown', dismiss);
      window.removeEventListener('keydown', onEscape);
    };
  }, [onClose, state]);

  if (!state) return null;

  const actions: Action[] = state.hasSelection
    ? [
        { key: 'copy', label: t('menuCopy'), run: onCopy },
        { key: 'duplicate', label: t('menuDuplicate'), run: onDuplicate },
        {
          key: 'paste',
          label: t('menuPaste'),
          run: () => onPaste({ x: state.x, y: state.y }),
          disabled: !canPaste,
        },
        { key: 'delete', label: t('menuDelete'), run: onDelete, danger: true },
      ]
    : [
        { key: 'note', label: t('menuAddNote'), run: () => onAddNote({ x: state.x, y: state.y }) },
        {
          key: 'paste',
          label: t('menuPaste'),
          run: () => onPaste({ x: state.x, y: state.y }),
          disabled: !canPaste,
        },
      ];

  return (
    <div
      ref={ref}
      role="menu"
      aria-label={t('menuLabel')}
      style={{ left: state.x, top: state.y }}
      className="fixed z-50 min-w-40 rounded-[var(--radius-md)] border border-border bg-surface py-1 shadow-raised"
    >
      {actions.map((action) => (
        <button
          key={action.key}
          type="button"
          role="menuitem"
          disabled={action.disabled}
          onClick={() => {
            action.run();
            onClose();
          }}
          className={`block w-full px-3 py-1.5 text-left text-sm transition-colors hover:bg-surface-soft disabled:cursor-not-allowed disabled:opacity-50 ${
            action.danger ? 'text-danger' : 'text-text'
          }`}
        >
          {action.label}
        </button>
      ))}
    </div>
  );
}
