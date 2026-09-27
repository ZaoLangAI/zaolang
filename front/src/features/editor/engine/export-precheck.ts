/**
 * Structural (pixel-free) sanity checks over a handful of sampled ticks —
 * built on the same `resolveFrame` the live preview and export runner use,
 * so "would this frame actually show anything" never drifts from what
 * really gets rendered. Deliberately kept DOM-free so it's cheap to run on
 * every document change and unit-testable without a browser.
 */
import { resolveFrame, type ActiveClipLayer, type FrameLayers } from './compositor';
import type { CanonicalDocument } from './ports';

export type PrecheckIssueKind = 'blank_frame' | 'clip_off_canvas';

export interface PrecheckIssue {
  kind: PrecheckIssueKind;
  atTicks: number;
}

export interface PrecheckSample {
  atTicks: number;
  frame: FrameLayers;
}

export interface ExportPrecheckResult {
  samples: PrecheckSample[];
  issues: PrecheckIssue[];
}

/** Evenly spaced tick offsets across `[0, durationTicks)`, e.g. 0%/25%/50%/75%/100% for `sampleCount = 5`. */
export function sampleTicks(durationTicks: number, sampleCount: number): number[] {
  const lastTick = Math.max(0, Math.max(durationTicks, 1) - 1);
  if (sampleCount <= 1) return [0];
  const ticks: number[] = [];
  for (let i = 0; i < sampleCount; i++) {
    ticks.push(Math.round((i / (sampleCount - 1)) * lastTick));
  }
  return ticks;
}

/**
 * The visible clip is drawn cover-fit onto a canvas-sized layer, then
 * panned/scaled/rotated around the canvas centre (see `drawClipTransformed`
 * in `compositor.ts`) — this mirrors that same math to get the transformed
 * layer's axis-aligned bounding box, and flags it when that box no longer
 * overlaps the canvas at all (a keyframed pan/zoom that drifted the picture
 * fully off-frame, or a scale of 0).
 */
function isClipOffCanvas(
  clip: ActiveClipLayer,
  canvasWidth: number,
  canvasHeight: number,
): boolean {
  const scale = clip.transform.scaleMillipercent / 100_000;
  if (scale <= 0) return true;
  const xOffsetPx = (clip.transform.xMilli / 1000) * canvasWidth;
  const yOffsetPx = (clip.transform.yMilli / 1000) * canvasHeight;
  const rotationRadians = (clip.transform.rotationMillidegrees / 1000) * (Math.PI / 180);
  const halfWidth = (canvasWidth * scale) / 2;
  const halfHeight = (canvasHeight * scale) / 2;
  const cos = Math.abs(Math.cos(rotationRadians));
  const sin = Math.abs(Math.sin(rotationRadians));
  const extentX = halfWidth * cos + halfHeight * sin;
  const extentY = halfWidth * sin + halfHeight * cos;
  const centerX = canvasWidth / 2 + xOffsetPx;
  const centerY = canvasHeight / 2 + yOffsetPx;
  const left = centerX - extentX;
  const right = centerX + extentX;
  const top = centerY - extentY;
  const bottom = centerY + extentY;
  return right <= 0 || left >= canvasWidth || bottom <= 0 || top >= canvasHeight;
}

function hasVisibleContent(frame: FrameLayers): boolean {
  return Boolean(frame.clip) || frame.captions.length > 0 || Boolean(frame.overlay);
}

export function runStructuralPrecheck(
  document: CanonicalDocument,
  durationTicks: number,
  sampleCount = 5,
): ExportPrecheckResult {
  const issues: PrecheckIssue[] = [];
  const samples = sampleTicks(durationTicks, sampleCount).map((atTicks) => {
    const frame = resolveFrame(document, atTicks);
    if (!hasVisibleContent(frame)) issues.push({ kind: 'blank_frame', atTicks });
    if (frame.clip && isClipOffCanvas(frame.clip, frame.canvasWidth, frame.canvasHeight)) {
      issues.push({ kind: 'clip_off_canvas', atTicks });
    }
    return { atTicks, frame };
  });
  return { samples, issues };
}
