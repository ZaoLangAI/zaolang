import type { CanvasNodeBinding, CanvasNodeKind } from './api';

/**
 * Dropping something onto the canvas.
 *
 * A custom MIME plus a validating reader, matching
 * `features/editor/timeline/dnd.ts` — the house convention. `text/plain`
 * would let any dragged text land as a card, and `dataTransfer` is readable
 * by any page the user drags across, so the payload is deliberately just ids
 * the server will re-check anyway.
 */

export const CANVAS_DRAG_MIME = 'application/x-zaolang-canvas-card';

export interface CanvasDragPayload {
  kind: CanvasNodeKind;
  label?: string;
  binding?: CanvasNodeBinding;
}

export function writeCanvasDrag(dataTransfer: DataTransfer, payload: CanvasDragPayload): void {
  dataTransfer.setData(CANVAS_DRAG_MIME, JSON.stringify(payload));
  dataTransfer.effectAllowed = 'copy';
}

export function hasCanvasDrag(dataTransfer: DataTransfer | null): boolean {
  return !!dataTransfer && dataTransfer.types.includes(CANVAS_DRAG_MIME);
}

/**
 * The payload, or `null` if this drag is not ours.
 *
 * Validated rather than cast: the data is a string from the DOM, and a drag
 * that started on another page can carry the same MIME with anything in it.
 */
export function readCanvasDrag(dataTransfer: DataTransfer | null): CanvasDragPayload | null {
  const raw = dataTransfer?.getData(CANVAS_DRAG_MIME);
  if (!raw) return null;
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return null;
  }
  if (typeof parsed !== 'object' || parsed === null) return null;
  const { kind, label, binding } = parsed as Partial<CanvasDragPayload>;
  if (typeof kind !== 'string') return null;
  return {
    kind: kind as CanvasNodeKind,
    ...(typeof label === 'string' ? { label } : {}),
    ...(typeof binding === 'object' && binding !== null ? { binding } : {}),
  };
}
