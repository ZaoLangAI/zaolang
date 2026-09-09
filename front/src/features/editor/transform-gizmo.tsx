'use client';

import { useTranslations } from 'next-intl';
import { useEffect, useRef, useState } from 'react';

import { IconRotate } from '@/components/ui/icons';

import { resolveNumberAtTime } from './engine/animation';
import type { AnimatableProperty, EditCommand, TimelineElement } from './engine/ports';

const X_RANGE = 2000;
const SCALE_MIN = 10_000;
const SCALE_MAX = 500_000;
const CENTER_SNAP_PX = 8;
const SCALE_SNAP_RATIO = 0.02;
const ROTATION_SNAP_DEGREES = 3;
const ROTATION_SNAP_TARGETS = [-180, -135, -90, -45, 0, 45, 90, 135, 180];

interface GizmoTransform {
  xMilli: number;
  yMilli: number;
  scaleMillipercent: number;
  rotationMillidegrees: number;
}

type HandleMode = 'move' | 'scale' | 'rotate';

interface DragState {
  mode: HandleMode;
  start: GizmoTransform;
  startClientX: number;
  startClientY: number;
  centerClientX: number;
  centerClientY: number;
  startDistance: number;
  startAngle: number;
  surfaceWidth: number;
  surfaceHeight: number;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

/** The element's transform at `atTicks` — the same resolution `compositor.ts` draws with. */
export function resolveTransform(element: TimelineElement, atTicks: number): GizmoTransform {
  const animations = element.animations;
  return {
    xMilli: resolveNumberAtTime(animations, 'transform.x_milli', atTicks, 0),
    yMilli: resolveNumberAtTime(animations, 'transform.y_milli', atTicks, 0),
    scaleMillipercent: resolveNumberAtTime(animations, 'transform.scale_millipercent', atTicks, 100_000),
    rotationMillidegrees: resolveNumberAtTime(animations, 'transform.rotation_millidegrees', atTicks, 0),
  };
}

/**
 * Where a gizmo/number-field edit of `property` should write: a channel
 * with no keyframes yet gets a single point at the element's start (which
 * the renderer treats as a static value), an animated channel gets the
 * point at the playhead, clamped inside the element so it always affects
 * what is on screen.
 */
export function keyframeTickFor(
  element: TimelineElement,
  property: AnimatableProperty,
  playheadTicks: number,
): number {
  const points = element.animations.channels[property]?.points ?? [];
  if (points.length === 0) return element.start_ticks;
  return clamp(playheadTicks, element.start_ticks, element.start_ticks + element.duration_ticks - 1);
}

/** `set_keyframe` commands for every channel whose value differs from `before`. */
export function transformCommands(
  element: TimelineElement,
  before: GizmoTransform,
  after: GizmoTransform,
  playheadTicks: number,
): EditCommand[] {
  const commands: EditCommand[] = [];
  const push = (property: 'transform.x_milli' | 'transform.y_milli' | 'transform.scale_millipercent' | 'transform.rotation_millidegrees', value: number) => {
    commands.push({
      type: 'set_keyframe',
      element_id: element.id,
      property,
      at_ticks: keyframeTickFor(element, property, playheadTicks),
      value: Math.round(value),
    });
  };
  if (Math.round(after.xMilli) !== Math.round(before.xMilli)) push('transform.x_milli', clamp(after.xMilli, -X_RANGE, X_RANGE));
  if (Math.round(after.yMilli) !== Math.round(before.yMilli)) push('transform.y_milli', clamp(after.yMilli, -X_RANGE, X_RANGE));
  if (Math.round(after.scaleMillipercent) !== Math.round(before.scaleMillipercent)) {
    push('transform.scale_millipercent', clamp(after.scaleMillipercent, SCALE_MIN, SCALE_MAX));
  }
  if (Math.round(after.rotationMillidegrees) !== Math.round(before.rotationMillidegrees)) {
    let degrees = after.rotationMillidegrees / 1000;
    while (degrees > 180) degrees -= 360;
    while (degrees < -180) degrees += 360;
    push('transform.rotation_millidegrees', degrees * 1000);
  }
  return commands;
}

/**
 * On-canvas transform handles for the selected clip/sticker: drag the box
 * to pan, a corner to scale, the top handle to rotate. Snaps the centre to
 * the canvas centre, scale to 100% and rotation to 45° steps unless Shift
 * is held. Commits as `set_keyframe`s (see `transformCommands`) on release;
 * while dragging only the outline moves, the frame itself updates the
 * moment the (local, optimistic) command lands.
 *
 * Must sit inside the same `data-mask-surface` box `MaskOverlay` uses, so
 * pixel deltas map onto the canvas's own coordinate space.
 */
export function TransformGizmo({
  element,
  playheadTicks,
  disabled,
  snappingEnabled,
  onCommit,
}: {
  element: TimelineElement;
  playheadTicks: number;
  disabled: boolean;
  snappingEnabled: boolean;
  onCommit: (commands: EditCommand[]) => void;
}) {
  const t = useTranslations('editor');
  const rootRef = useRef<HTMLDivElement | null>(null);
  const [surface, setSurface] = useState({ width: 0, height: 0 });
  const [live, setLive] = useState<GizmoTransform | null>(null);
  const dragRef = useRef<DragState | null>(null);
  const liveRef = useRef<GizmoTransform | null>(null);

  useEffect(() => {
    const host = rootRef.current?.closest('[data-mask-surface]');
    if (!(host instanceof HTMLElement)) return;
    const measure = () => {
      const rect = host.getBoundingClientRect();
      setSurface({ width: rect.width, height: rect.height });
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(host);
    return () => observer.disconnect();
  }, []);

  const activeListenersRef = useRef<{
    onMove: (event: PointerEvent) => void;
    onUp: () => void;
  } | null>(null);

  // A drag started via `begin()` attaches listeners straight to `window`;
  // if the component unmounts mid-drag (e.g. the element is deleted while
  // a pointer button is still held), `onUp` never fires to remove them.
  useEffect(() => {
    return () => {
      const active = activeListenersRef.current;
      if (!active) return;
      window.removeEventListener('pointermove', active.onMove);
      window.removeEventListener('pointerup', active.onUp);
      activeListenersRef.current = null;
      dragRef.current = null;
    };
  }, []);

  const resolved = resolveTransform(element, playheadTicks);
  const current = live ?? resolved;

  const begin = (event: React.PointerEvent<HTMLElement>, mode: HandleMode) => {
    if (disabled || event.button !== 0) return;
    event.stopPropagation();
    event.preventDefault();
    const host = rootRef.current?.closest('[data-mask-surface]');
    if (!(host instanceof HTMLElement)) return;
    const rect = host.getBoundingClientRect();
    const centerClientX = rect.left + rect.width / 2 + (resolved.xMilli / 1000) * rect.width;
    const centerClientY = rect.top + rect.height / 2 + (resolved.yMilli / 1000) * rect.height;
    const start: DragState = {
      mode,
      start: resolved,
      startClientX: event.clientX,
      startClientY: event.clientY,
      centerClientX,
      centerClientY,
      startDistance: Math.max(1, Math.hypot(event.clientX - centerClientX, event.clientY - centerClientY)),
      startAngle: Math.atan2(event.clientY - centerClientY, event.clientX - centerClientX),
      surfaceWidth: rect.width,
      surfaceHeight: rect.height,
    };
    dragRef.current = start;
    liveRef.current = resolved;
    setLive(resolved);

    const onMove = (move: PointerEvent) => {
      const drag = dragRef.current;
      if (!drag) return;
      const snap = snappingEnabled !== move.shiftKey;
      let next: GizmoTransform = drag.start;
      if (drag.mode === 'move') {
        let dx = move.clientX - drag.startClientX;
        let dy = move.clientY - drag.startClientY;
        if (snap) {
          const centerX = drag.surfaceWidth / 2 + (drag.start.xMilli / 1000) * drag.surfaceWidth + dx;
          const centerY = drag.surfaceHeight / 2 + (drag.start.yMilli / 1000) * drag.surfaceHeight + dy;
          if (Math.abs(centerX - drag.surfaceWidth / 2) <= CENTER_SNAP_PX) dx -= centerX - drag.surfaceWidth / 2;
          if (Math.abs(centerY - drag.surfaceHeight / 2) <= CENTER_SNAP_PX) dy -= centerY - drag.surfaceHeight / 2;
        }
        next = {
          ...drag.start,
          xMilli: clamp(drag.start.xMilli + (dx / drag.surfaceWidth) * 1000, -X_RANGE, X_RANGE),
          yMilli: clamp(drag.start.yMilli + (dy / drag.surfaceHeight) * 1000, -X_RANGE, X_RANGE),
        };
      } else if (drag.mode === 'scale') {
        const distance = Math.hypot(move.clientX - drag.centerClientX, move.clientY - drag.centerClientY);
        let scale = (drag.start.scaleMillipercent * distance) / drag.startDistance;
        if (snap && Math.abs(scale - 100_000) <= 100_000 * SCALE_SNAP_RATIO) scale = 100_000;
        next = { ...drag.start, scaleMillipercent: clamp(scale, SCALE_MIN, SCALE_MAX) };
      } else {
        const angle = Math.atan2(move.clientY - drag.centerClientY, move.clientX - drag.centerClientX);
        let degrees = drag.start.rotationMillidegrees / 1000 + ((angle - drag.startAngle) * 180) / Math.PI;
        while (degrees > 180) degrees -= 360;
        while (degrees < -180) degrees += 360;
        if (snap) {
          const target = ROTATION_SNAP_TARGETS.find((candidate) => Math.abs(candidate - degrees) <= ROTATION_SNAP_DEGREES);
          if (target !== undefined) degrees = target;
        }
        next = { ...drag.start, rotationMillidegrees: degrees * 1000 };
      }
      liveRef.current = next;
      setLive(next);
    };
    const onUp = () => {
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
      activeListenersRef.current = null;
      const drag = dragRef.current;
      dragRef.current = null;
      setLive(null);
      if (!drag || !liveRef.current) return;
      const commands = transformCommands(element, drag.start, liveRef.current, playheadTicks);
      if (commands.length) onCommit(commands);
    };
    activeListenersRef.current = { onMove, onUp };
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
  };

  const scale = current.scaleMillipercent / 100_000;
  const boxWidth = surface.width * scale;
  const boxHeight = surface.height * scale;
  const centerX = surface.width / 2 + (current.xMilli / 1000) * surface.width;
  const centerY = surface.height / 2 + (current.yMilli / 1000) * surface.height;
  const rotation = current.rotationMillidegrees / 1000;

  const cornerClass =
    'absolute size-3 rounded-sm border border-primary bg-white shadow-sm pointer-events-auto';

  return (
    <div ref={rootRef} className="pointer-events-none absolute inset-0 overflow-visible" aria-hidden={disabled}>
      {surface.width > 0 ? (
        <div
          className="absolute"
          style={{
            left: centerX - boxWidth / 2,
            top: centerY - boxHeight / 2,
            width: boxWidth,
            height: boxHeight,
            transform: `rotate(${rotation}deg)`,
          }}
        >
          <div
            role="presentation"
            title={t('gizmoMove')}
            onPointerDown={(event) => begin(event, 'move')}
            className={`absolute inset-0 border ${live ? 'border-primary' : 'border-primary/80'} ${
              disabled ? '' : 'pointer-events-auto cursor-move'
            }`}
          />
          {!disabled ? (
            <>
              <span onPointerDown={(event) => begin(event, 'scale')} className={`${cornerClass} -left-1.5 -top-1.5 cursor-nwse-resize`} title={t('gizmoScale')} />
              <span onPointerDown={(event) => begin(event, 'scale')} className={`${cornerClass} -right-1.5 -top-1.5 cursor-nesw-resize`} title={t('gizmoScale')} />
              <span onPointerDown={(event) => begin(event, 'scale')} className={`${cornerClass} -bottom-1.5 -left-1.5 cursor-nesw-resize`} title={t('gizmoScale')} />
              <span onPointerDown={(event) => begin(event, 'scale')} className={`${cornerClass} -bottom-1.5 -right-1.5 cursor-nwse-resize`} title={t('gizmoScale')} />
              <span className="absolute left-1/2 top-0 h-6 w-px -translate-x-1/2 -translate-y-full bg-primary/80" />
              <button
                type="button"
                title={t('gizmoRotate')}
                aria-label={t('gizmoRotate')}
                onPointerDown={(event) => begin(event, 'rotate')}
                className="pointer-events-auto absolute left-1/2 top-0 flex size-5 -translate-x-1/2 -translate-y-[calc(100%+1.25rem)] cursor-grab items-center justify-center rounded-full border border-primary bg-white text-primary shadow-sm"
              >
                <IconRotate className="size-3" />
              </button>
            </>
          ) : null}
          {live ? (
            <span className="pointer-events-none absolute left-1/2 top-full mt-1 -translate-x-1/2 whitespace-nowrap rounded bg-black/70 px-1.5 py-0.5 font-mono text-[10px] text-white">
              {Math.round(live.xMilli / 10)}%, {Math.round(live.yMilli / 10)}% · {Math.round(live.scaleMillipercent / 1000)}% ·{' '}
              {Math.round(live.rotationMillidegrees / 1000)}°
            </span>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
