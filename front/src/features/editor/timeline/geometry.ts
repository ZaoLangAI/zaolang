/**
 * DOM-free timeline math: zoom ↔ pixels-per-tick, ruler tick spacing,
 * timecode formatting and snapping. Kept pure so the interaction rules the
 * timeline relies on (OpenCut-style 10px snap, exponential wheel zoom,
 * `HH:MM:SS:FF` display) can be unit-tested without a browser.
 */

import { TICKS_PER_SECOND, type CanonicalDocument, type CanvasSpec } from '../engine/ports';

/** Pixels one second of timeline occupies at zoom 1 — matches OpenCut's base. */
export const BASE_PX_PER_SECOND = 50;
export const ZOOM_MIN = 0.05;
export const ZOOM_MAX = 40;
/** Multiplier used by the −/+ zoom buttons. */
export const ZOOM_BUTTON_FACTOR = 1.7;
/** Snap distance in screen pixels — constant "feel" regardless of zoom. */
export const SNAP_PX_THRESHOLD = 10;
/** Pointer travel before a press turns into a drag (vs. a click). */
export const DRAG_THRESHOLD_PX = 5;
/** Distance from a scroll container's edge at which dragging auto-scrolls it, and the fastest it scrolls. */
export const EDGE_AUTO_SCROLL_PX = 100;
export const EDGE_AUTO_SCROLL_MAX_SPEED = 15;
export const MIN_ELEMENT_DURATION_TICKS = Math.round(TICKS_PER_SECOND * 0.1);

export function clampZoom(zoom: number): number {
  return Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, zoom));
}

export function pxPerTick(zoom: number): number {
  return (BASE_PX_PER_SECOND * zoom) / TICKS_PER_SECOND;
}

export function ticksToPx(ticks: number, zoom: number): number {
  return ticks * pxPerTick(zoom);
}

export function pxToTicks(px: number, zoom: number): number {
  return Math.round(px / pxPerTick(zoom));
}

/**
 * Exponential zoom for Ctrl/Cmd+wheel: a single notch is capped so a
 * high-resolution trackpad flick can't jump from fit-to-view to max.
 */
export function wheelZoomFactor(deltaY: number): number {
  const clamped = Math.max(-30, Math.min(30, deltaY));
  return Math.exp(-clamped / 300);
}

/** Slider position 0..1 ↔ zoom, exponential so both ends feel evenly spaced. */
export function zoomFromSlider(value: number): number {
  const t = Math.min(1, Math.max(0, value));
  return clampZoom(ZOOM_MIN * Math.pow(ZOOM_MAX / ZOOM_MIN, t));
}

export function sliderFromZoom(zoom: number): number {
  const clamped = clampZoom(zoom);
  return Math.log(clamped / ZOOM_MIN) / Math.log(ZOOM_MAX / ZOOM_MIN);
}

/** Zoom level that fits `spanTicks` into `viewportPx` with a little breathing room. */
export function zoomToFit(spanTicks: number, viewportPx: number): number {
  const span = Math.max(spanTicks, TICKS_PER_SECOND);
  const usable = Math.max(1, viewportPx * 0.95);
  return clampZoom((usable / span) * (TICKS_PER_SECOND / BASE_PX_PER_SECOND));
}

export function frameTicks(canvas: CanvasSpec): number {
  return Math.max(1, Math.round((TICKS_PER_SECOND * canvas.fps_den) / canvas.fps_num));
}

export function canvasFps(canvas: CanvasSpec): number {
  return Math.max(1, canvas.fps_num / Math.max(1, canvas.fps_den));
}

/** Rounds to the nearest whole frame so scrubbing/stepping never lands between frames. */
export function snapToFrame(ticks: number, canvas: CanvasSpec): number {
  const frame = frameTicks(canvas);
  return Math.max(0, Math.round(ticks / frame) * frame);
}

/** `HH:MM:SS:FF` — the NLE convention, frames instead of decimals. */
export function formatTimecode(ticks: number, fps: number): string {
  const safe = Math.max(0, ticks);
  const totalSeconds = Math.floor(safe / TICKS_PER_SECOND);
  const remainderTicks = safe - totalSeconds * TICKS_PER_SECOND;
  const frames = Math.min(
    Math.max(1, Math.round(fps)) - 1,
    Math.floor((remainderTicks / TICKS_PER_SECOND) * fps),
  );
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  const pad = (value: number) => String(value).padStart(2, '0');
  return `${pad(hours)}:${pad(minutes)}:${pad(seconds)}:${pad(frames)}`;
}

/** Short `3.20s` style label for clip badges and marker chips. */
export function formatSeconds(ticks: number, digits = 2): string {
  return `${(ticks / TICKS_PER_SECOND).toFixed(digits)}s`;
}

const RULER_INTERVALS_SECONDS = [0.1, 0.25, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600];

export interface RulerScale {
  /** Seconds between labelled major ticks. */
  majorSeconds: number;
  /** Minor ticks per major interval. */
  minorPerMajor: number;
}

/** Picks the coarsest interval whose major ticks stay at least `minMajorPx` apart. */
export function rulerScale(zoom: number, minMajorPx = 80): RulerScale {
  const pxPerSecond = BASE_PX_PER_SECOND * zoom;
  const majorSeconds =
    RULER_INTERVALS_SECONDS.find((seconds) => seconds * pxPerSecond >= minMajorPx) ??
    RULER_INTERVALS_SECONDS[RULER_INTERVALS_SECONDS.length - 1]!;
  const minorPerMajor = majorSeconds >= 60 ? 6 : majorSeconds >= 5 ? 5 : majorSeconds >= 1 ? 4 : 2;
  return { majorSeconds, minorPerMajor };
}

export interface RulerTick {
  ticks: number;
  major: boolean;
}

/** Every tick mark (major + minor) between `fromTicks` and `toTicks`. */
export function rulerTicks(zoom: number, fromTicks: number, toTicks: number): RulerTick[] {
  const { majorSeconds, minorPerMajor } = rulerScale(zoom);
  const minorTicks = Math.max(1, Math.round((majorSeconds * TICKS_PER_SECOND) / minorPerMajor));
  const start = Math.max(0, Math.floor(fromTicks / minorTicks) * minorTicks);
  const out: RulerTick[] = [];
  for (
    let at = start, index = Math.round(start / minorTicks);
    at <= toTicks;
    at += minorTicks, index++
  ) {
    out.push({ ticks: at, major: index % minorPerMajor === 0 });
  }
  return out;
}

export interface SnapResult {
  ticks: number;
  snapped: boolean;
  /** The target that won, when one did. */
  target: number | null;
}

/** Nearest target within `thresholdTicks`, else the candidate unchanged. */
export function snapTick(
  candidate: number,
  targets: Iterable<number>,
  thresholdTicks: number,
): SnapResult {
  let best = candidate;
  let bestDistance = thresholdTicks;
  let hit: number | null = null;
  for (const target of targets) {
    const distance = Math.abs(candidate - target);
    if (distance <= bestDistance) {
      bestDistance = distance;
      best = target;
      hit = target;
    }
  }
  return { ticks: best, snapped: hit !== null, target: hit };
}

/**
 * Where a dragged element can land: 0, the playhead, every other element's
 * two edges and every marker. `excludeIds` keeps a dragged group from
 * snapping to itself.
 */
export function collectSnapTargets(
  document: CanonicalDocument,
  options: {
    excludeIds?: Iterable<string>;
    playheadTicks?: number | null;
    includeMarkers?: boolean;
  } = {},
): number[] {
  const exclude = new Set(options.excludeIds ?? []);
  const targets = new Set<number>([0]);
  if (options.playheadTicks != null) targets.add(options.playheadTicks);
  for (const track of document.tracks) {
    for (const element of track.elements) {
      if (exclude.has(element.id)) continue;
      targets.add(element.start_ticks);
      targets.add(element.start_ticks + element.duration_ticks);
    }
  }
  if (options.includeMarkers !== false) {
    for (const marker of document.markers) targets.add(marker.at_ticks);
  }
  return [...targets];
}

/** Ids of every element whose span covers `atTicks` (strictly inside, so an edge is not "under"). */
export function elementIdsUnderTick(document: CanonicalDocument, atTicks: number): string[] {
  const ids: string[] = [];
  for (const track of document.tracks) {
    for (const element of track.elements) {
      if (atTicks > element.start_ticks && atTicks < element.start_ticks + element.duration_ticks) {
        ids.push(element.id);
      }
    }
  }
  return ids;
}

/** Speed (px per frame, signed) for edge auto-scroll given the pointer's distance to the container edges. */
export function edgeAutoScrollSpeed(
  pointerPx: number,
  containerStartPx: number,
  containerEndPx: number,
): number {
  const fromStart = pointerPx - containerStartPx;
  const fromEnd = containerEndPx - pointerPx;
  if (fromStart < EDGE_AUTO_SCROLL_PX) {
    const ratio = 1 - Math.max(0, fromStart) / EDGE_AUTO_SCROLL_PX;
    return -Math.ceil(ratio * EDGE_AUTO_SCROLL_MAX_SPEED);
  }
  if (fromEnd < EDGE_AUTO_SCROLL_PX) {
    const ratio = 1 - Math.max(0, fromEnd) / EDGE_AUTO_SCROLL_PX;
    return Math.ceil(ratio * EDGE_AUTO_SCROLL_MAX_SPEED);
  }
  return 0;
}

/** Whether two half-open ranges overlap — used by marquee selection. */
export function rangesOverlap(aStart: number, aEnd: number, bStart: number, bEnd: number): boolean {
  return aStart < bEnd && bStart < aEnd;
}
