'use client';

import { useTranslations } from 'next-intl';
import { useCallback, useRef, useState } from 'react';
import { createPortal } from 'react-dom';

import { Button } from '@/components/ui/button';
import { TextInput } from '@/components/ui/field';
import { IconClose, IconSparkle } from '@/components/ui/icons';
import { Badge, ErrorNotice, type BadgeTone } from '@/components/ui/primitives';
import { Spinner } from '@/components/ui/spinner';
import type { PromptEnhancePayload, PromptEnhanceResult } from '@/lib/api/types';
import { cn } from '@/lib/cn';
import { loadAnime, useIsomorphicLayoutEffect, useReducedMotion } from '@/lib/motion';
import { useOverlayTransition } from '@/lib/use-overlay-transition';

export type Direction = NonNullable<PromptEnhancePayload['direction']>;
type DetailLevel = PromptEnhanceResult['detail_level'];

export const DIRECTIONS: readonly Direction[] = [
  'more_specific',
  'more_concise',
  'stronger_camera',
  'stronger_lighting',
  'more_dramatic',
];

// Camera work is meaningless on a still, so that direction is hidden there
// rather than offered and then ignored by the agent.
export const VIDEO_ONLY_DIRECTIONS: readonly Direction[] = ['stronger_camera'];

const DETAIL_TONE: Record<DetailLevel, BadgeTone> = {
  sparse: 'danger',
  adequate: 'amber',
  detailed: 'success',
};

const ENTER_DURATION = 260;
const EXIT_DURATION = 200;
const RISE_DISTANCE = 32;

// Bounds for the drag-to-resize handle: short enough to still show its
// header, short of swallowing the whole viewport on a determined drag.
const MIN_PANEL_HEIGHT = 160;
const MAX_PANEL_HEIGHT_RATIO = 0.9;

/**
 * The "AI 润色" result panel, as a bottom drawer.
 *
 * Deliberately **not** built on `ui/sheet.tsx`: that component's contract is
 * modal on purpose (backdrop, Escape-to-close, click-outside-to-close, focus
 * trap, locked page scroll — see its own docstring), and this panel needs the
 * opposite of every one of those so the author can keep editing the prompt
 * field, or any other control on the page, while it stays open. There is no
 * backdrop element at all (nothing to intercept a click), no `Escape`
 * listener, no focus trap and no `document.body.style.overflow` write — the
 * only way to dismiss it is the close button in the top-right corner.
 *
 * Kept scoped to this feature rather than promoted to `ui/`: it is the only
 * non-modal drawer in the product today, and its content (diagnosis badge,
 * dimension checklist, direction chips, follow-up input) is specific to "AI
 * 润色", not a generic slot-based shell.
 */
export function PromptPolishDrawer({
  open,
  onClose,
  pending,
  error,
  suggestion,
  instruction,
  onInstructionChange,
  directions,
  onDirection,
  onRefine,
  onAutofill,
}: {
  open: boolean;
  onClose: () => void;
  pending: boolean;
  error: string | null;
  suggestion: PromptEnhanceResult | null;
  instruction: string;
  onInstructionChange: (value: string) => void;
  directions: readonly Direction[];
  onDirection: (direction: Direction) => void;
  onRefine: () => void;
  onAutofill: () => void;
}) {
  const t = useTranslations('promptPolish');
  const tActions = useTranslations('actions');
  const panelRef = useRef<HTMLDivElement>(null);
  const reduced = useReducedMotion();

  // Explicit height once the author drags the handle; otherwise the panel
  // just follows its default (content-driven, capped by `max-h-[33dvh]`).
  const [heightPx, setHeightPx] = useState<number | null>(null);
  const resizeRef = useRef<{ startClientY: number; startHeight: number } | null>(null);

  const beginResize = useCallback((event: React.PointerEvent<HTMLDivElement>) => {
    const panel = panelRef.current;
    if (!panel) return;
    event.preventDefault();
    resizeRef.current = {
      startClientY: event.clientY,
      startHeight: panel.getBoundingClientRect().height,
    };
    const maxHeight = window.innerHeight * MAX_PANEL_HEIGHT_RATIO;

    const onMove = (moveEvent: PointerEvent) => {
      const drag = resizeRef.current;
      if (!drag) return;
      // The panel is bottom-anchored, so dragging the handle *up* (a
      // smaller clientY) is what grows it — hence the flipped subtraction.
      const next = drag.startClientY - moveEvent.clientY + drag.startHeight;
      setHeightPx(Math.min(maxHeight, Math.max(MIN_PANEL_HEIGHT, next)));
    };
    const onUp = () => {
      resizeRef.current = null;
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
    };
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
  }, []);

  const animateExit = useCallback(async (signal: AbortSignal) => {
    const { animate } = await loadAnime();
    if (signal.aborted) return;
    const panel = panelRef.current;
    if (!panel) return;
    await animate(panel, {
      opacity: [1, 0],
      translateY: [0, RISE_DISTANCE],
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
        translateY: [RISE_DISTANCE, 0],
        duration: ENTER_DURATION,
        ease: 'outExpo',
      });
    });
  }, [render, reduced]);

  // Non-modal means the page underneath stays fully interactive, but it is
  // still a `fixed` panel sitting on top of it — without this, whatever the
  // last block of content is (a footer, a submit bar) becomes permanently
  // unreachable by scrolling once the drawer is tall enough to cover it.
  // Reserving that much space at the end of the document, kept in sync with
  // a `ResizeObserver` since the panel's height changes with its content
  // and with the drag handle above, lets the page scroll the same content
  // fully clear of the drawer instead.
  useIsomorphicLayoutEffect(() => {
    if (!render || typeof document === 'undefined') return;
    const panel = panelRef.current;
    if (!panel) return;
    const previousPaddingBottom = document.body.style.paddingBottom;
    const applyPadding = () => {
      document.body.style.paddingBottom = `${panel.getBoundingClientRect().height}px`;
    };
    applyPadding();
    const observer = new ResizeObserver(applyPadding);
    observer.observe(panel);
    return () => {
      observer.disconnect();
      document.body.style.paddingBottom = previousPaddingBottom;
    };
  }, [render]);

  if (!render || typeof document === 'undefined') return null;

  return createPortal(
    <div
      ref={panelRef}
      role="dialog"
      aria-modal="false"
      aria-label={t('drawerTitle')}
      aria-busy={pending || undefined}
      className={cn(
        'fixed inset-x-0 bottom-0 z-40 flex max-h-[33dvh] w-full flex-col',
        'rounded-t-[var(--radius-lg)] border border-b-0 border-border bg-surface-raised shadow-raised',
        'safe-b outline-none',
      )}
      style={heightPx != null ? { height: heightPx, maxHeight: heightPx } : undefined}
    >
      <div
        role="separator"
        aria-orientation="horizontal"
        aria-label={t('resizeHandle')}
        onPointerDown={beginResize}
        className="flex h-3 shrink-0 cursor-row-resize touch-none items-center justify-center"
      >
        <span aria-hidden="true" className="h-1 w-10 rounded-full bg-border" />
      </div>

      <header className="border-b border-border">
        <div className="mx-auto flex max-w-[1440px] items-center gap-2 px-5 py-1.5">
          <IconSparkle className="size-3.5 shrink-0 text-primary" aria-hidden="true" />
          <h2 className="min-w-0 flex-1 truncate text-xs font-semibold">{t('drawerTitle')}</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label={tActions('close')}
            className={cn(
              'grid size-6 shrink-0 place-items-center rounded-[var(--radius-sm)] text-muted transition-colors',
              'hover:bg-surface-soft hover:text-text focus-visible:outline-2',
            )}
          >
            <IconClose className="size-3.5" />
          </button>
        </div>
      </header>

      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
        <div className="mx-auto flex w-full max-w-[1440px] flex-1 flex-col gap-3 px-5 py-4">
          {error ? <ErrorNotice title={error} /> : null}

          {!error && pending && !suggestion ? (
            <div className="flex items-center gap-2 py-6 text-sm text-muted">
              <Spinner className="size-4" />
              {t('drawerPendingHint')}
            </div>
          ) : null}

          {suggestion ? (
            // Squeezed into a third of the viewport now, so the two panes
            // split by what the author actually looks at vs. acts on: the
            // left half is the text itself plus the box that keeps
            // rewriting it (the thing that needs the most reading room),
            // and the right half is everything else — the diagnosis that
            // explains *why*, and the quick "keep tweaking this version"
            // direction chips, both of which are short and scan-able.
            <div className="grid flex-1 grid-cols-1 gap-5 lg:grid-cols-2 lg:gap-8">
              <div className="flex min-h-0 flex-col gap-2">
                <div className="min-h-0 flex-1 overflow-y-auto rounded-[var(--radius-sm)] bg-surface-soft p-3">
                  <p className="text-sm leading-relaxed text-text">{suggestion.prompt}</p>
                </div>
                <div className="flex items-end gap-2">
                  <div className="min-w-0 flex-1">
                    <TextInput
                      label={t('instructionLabel')}
                      placeholder={t('instructionPlaceholder')}
                      value={instruction}
                      maxLength={200}
                      onChange={(event) => onInstructionChange(event.target.value)}
                      onKeyDown={(event) => {
                        if (event.key !== 'Enter' || !instruction.trim() || pending) return;
                        event.preventDefault();
                        onRefine();
                      }}
                    />
                  </div>
                  <Button
                    size="sm"
                    variant="secondary"
                    disabled={instruction.trim().length === 0 || pending}
                    loading={pending}
                    onClick={onRefine}
                  >
                    {t('refineApply')}
                  </Button>
                  <Button size="sm" onClick={onAutofill}>
                    {t('accept')}
                  </Button>
                </div>
              </div>

              <div className="flex min-h-0 flex-col gap-3 overflow-y-auto">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge tone={DETAIL_TONE[suggestion.detail_level]}>
                    {t(`detail.${suggestion.detail_level}`)}
                  </Badge>
                  <p className="min-w-0 flex-1 text-xs text-muted">{suggestion.feedback}</p>
                </div>

                {suggestion.dimensions && suggestion.dimensions.length > 0 ? (
                  <ul className="flex flex-col gap-1.5">
                    {suggestion.dimensions.map((dimension) => (
                      <li key={dimension.key} className="flex items-start gap-2 text-xs">
                        <span
                          aria-hidden="true"
                          className={cn(
                            'mt-1.5 size-1.5 shrink-0 rounded-full',
                            dimension.status === 'missing' && 'bg-danger',
                            dimension.status === 'weak' && 'bg-amber',
                            dimension.status === 'ok' && 'bg-success',
                          )}
                        />
                        <span className="w-14 shrink-0 font-medium">
                          {t(`dimension.${dimension.key}`)}
                        </span>
                        <span className="sr-only">{t(`status.${dimension.status}`)}</span>
                        <span className="min-w-0 flex-1 leading-relaxed text-muted">
                          {dimension.hint}
                        </span>
                      </li>
                    ))}
                  </ul>
                ) : null}

                {suggestion.additions && suggestion.additions.length > 0 ? (
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="text-[11px] text-muted">{t('addedLabel')}</span>
                    {suggestion.additions.map((addition) => (
                      <Badge key={addition} tone="primary">
                        {addition}
                      </Badge>
                    ))}
                  </div>
                ) : null}

                <div className="flex flex-col gap-1.5 border-t border-border pt-2.5">
                  <p className="text-[11px] text-muted">{t('refineLabel')}</p>
                  <div className="flex flex-wrap gap-1.5">
                    {directions.map((direction) => (
                      <button
                        key={direction}
                        type="button"
                        disabled={pending}
                        onClick={() => onDirection(direction)}
                        className="rounded-md border border-border px-2 py-1 text-xs text-muted transition-colors hover:border-primary/40 hover:text-primary disabled:opacity-50"
                      >
                        {t(`direction.${direction}`)}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          ) : null}
        </div>
      </div>
    </div>,
    document.body,
  );
}
