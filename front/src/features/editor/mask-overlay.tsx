'use client';

import { useTranslations } from 'next-intl';
import { useRef, useState } from 'react';

import type { ClipMask, EditCommand } from './engine/ports';

const MILLI_MAX = 1_000;
const MIN_SIZE_MILLI = 40;

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

interface DragState {
  mode: 'move' | 'resize';
  startClientX: number;
  startClientY: number;
  surfaceWidth: number;
  surfaceHeight: number;
  start: ClipMask;
}

/**
 * Draggable mask box drawn directly on the preview canvas, replacing the
 * "guess a percentage, type it into a number box, check the result"
 * round-trip `effects-mask-controls.tsx` required on its own. Coordinates
 * stay in the same 0-1000 "milli" space `effects.ts` renders the mask in
 * (see `drawMaskShape`), so percent-based CSS positioning here always
 * matches what actually gets cut out of the frame — no separate unit
 * conversion or canvas-size bookkeeping needed.
 *
 * Must be rendered inside a `position: relative` element carrying
 * `data-mask-surface` that exactly matches the canvas's own rendered box
 * (see `preview.tsx`), since drag deltas are measured against that
 * element's `getBoundingClientRect()`.
 */
export function MaskOverlay({
  mask,
  elementId,
  disabled,
  onCommit,
}: {
  mask: ClipMask;
  elementId: string;
  disabled: boolean;
  onCommit: (commands: EditCommand[]) => void;
}) {
  const t = useTranslations('editor');
  const [preview, setPreview] = useState(mask);
  // Mirrors `preview` synchronously (state updates are batched/async) so
  // `onUp` can read the just-computed value without calling `onCommit`
  // from inside a `setState` updater — doing that previously fired React's
  // "Cannot update a component while rendering a different component"
  // error, since `onCommit` (`apply()` in `drama-editor.tsx`) itself calls
  // `setBusy`/`setSaveStatus` on a different component.
  const previewRef = useRef(mask);
  const dragRef = useRef<DragState | null>(null);
  const [dragging, setDragging] = useState(false);

  const live = dragging ? preview : mask;

  const beginDrag = (event: React.PointerEvent<HTMLElement>, mode: DragState['mode']) => {
    if (disabled) return;
    event.stopPropagation();
    event.preventDefault();
    const surface = event.currentTarget.closest('[data-mask-surface]');
    if (!(surface instanceof HTMLElement)) return;
    const rect = surface.getBoundingClientRect();
    dragRef.current = {
      mode,
      startClientX: event.clientX,
      startClientY: event.clientY,
      surfaceWidth: rect.width,
      surfaceHeight: rect.height,
      start: mask,
    };
    previewRef.current = mask;
    setPreview(mask);
    setDragging(true);

    const onMove = (moveEvent: PointerEvent) => {
      const drag = dragRef.current;
      if (!drag) return;
      const deltaXMilli = ((moveEvent.clientX - drag.startClientX) / drag.surfaceWidth) * MILLI_MAX;
      const deltaYMilli = ((moveEvent.clientY - drag.startClientY) / drag.surfaceHeight) * MILLI_MAX;
      let next: ClipMask;
      if (drag.mode === 'move') {
        const x = clamp(drag.start.x_milli + deltaXMilli, 0, MILLI_MAX - drag.start.width_milli);
        const y = clamp(drag.start.y_milli + deltaYMilli, 0, MILLI_MAX - drag.start.height_milli);
        next = { ...drag.start, x_milli: Math.round(x), y_milli: Math.round(y) };
      } else {
        const width = clamp(drag.start.width_milli + deltaXMilli, MIN_SIZE_MILLI, MILLI_MAX - drag.start.x_milli);
        const height = clamp(drag.start.height_milli + deltaYMilli, MIN_SIZE_MILLI, MILLI_MAX - drag.start.y_milli);
        next = { ...drag.start, width_milli: Math.round(width), height_milli: Math.round(height) };
      }
      previewRef.current = next;
      setPreview(next);
    };

    const onUp = () => {
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
      dragRef.current = null;
      setDragging(false);
      onCommit([{ type: 'set_clip_mask', element_id: elementId, mask: previewRef.current }]);
    };

    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
  };

  return (
    <div className="pointer-events-none absolute inset-0">
      <div
        role="group"
        aria-label={t('maskOverlayLabel')}
        className={`pointer-events-auto absolute border-2 border-dashed border-primary bg-primary/10 ${
          mask.shape === 'ellipse' ? 'rounded-full' : ''
        } ${disabled ? 'cursor-default' : 'cursor-move'}`}
        style={{
          left: `${live.x_milli / 10}%`,
          top: `${live.y_milli / 10}%`,
          width: `${live.width_milli / 10}%`,
          height: `${live.height_milli / 10}%`,
        }}
        onPointerDown={(event) => beginDrag(event, 'move')}
      >
        <button
          type="button"
          aria-label={t('maskOverlayResize')}
          disabled={disabled}
          className="absolute -bottom-1.5 -right-1.5 size-3 cursor-nwse-resize rounded-full border border-surface bg-primary disabled:cursor-default"
          onPointerDown={(event) => beginDrag(event, 'resize')}
        />
      </div>
    </div>
  );
}
