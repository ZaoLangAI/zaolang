/**
 * Resolves a CanonicalDocument to the layers active at a given tick, and
 * draws them to a canvas. Shared by the live preview (per animation frame)
 * and the sequential export runner (per encoded frame) so both paths render
 * the same edited content instead of drifting apart.
 */

import { resolveNumberAtTime } from './animation';
import { applyClipEffects } from './effects';
import {
  TICKS_PER_SECOND,
  type BrandOverlay,
  type CanonicalDocument,
  type ClipEffect,
  type ClipMask,
  type ResolvedAsset,
  type TimelineElement,
  type TimelineTrack,
} from './ports';
import { WasmCompositor } from './wasm-compositor';

type Canvas2DContext = CanvasRenderingContext2D | OffscreenCanvasRenderingContext2D;

/** Resolved from `transform.*` keyframe channels (or the identity default) — see `animation.ts`. */
export interface ClipTransform {
  xMilli: number;
  yMilli: number;
  scaleMillipercent: number;
  rotationMillidegrees: number;
}

const IDENTITY_TRANSFORM: ClipTransform = {
  xMilli: 0,
  yMilli: 0,
  scaleMillipercent: 100_000,
  rotationMillidegrees: 0,
};

export interface ActiveClipLayer {
  asset_id: string;
  element_id: string;
  sourceSeconds: number;
  volume: number;
  effects: ClipEffect[];
  mask: ClipMask | null;
  /** Resolved 0-1 from the `opacity` channel (or 1, static default). */
  opacity: number;
  transform: ClipTransform;
}

/** One audio-producing element active at a tick — an audio-track clip, or the visible video clip's own sound. */
export interface ActiveAudioLayer {
  asset_id: string;
  element_id: string;
  track_id: string;
  sourceSeconds: number;
  volume: number;
  /** Playback-rate multiplier from the clip's own `speed_millipercent` — shifts pitch (no time-stretch), same tradeoff `set_clip_speed` already accepts for picture. */
  speedFactor: number;
}

export interface FrameLayers {
  canvasWidth: number;
  canvasHeight: number;
  clip: ActiveClipLayer | null;
  /** The other clip during a crossfade transition — null outside one, and always null for `dip_to_black` (which never shows two pictures at once). */
  transitionLayer: ActiveClipLayer | null;
  captions: string[];
  overlay: BrandOverlay | null;
}

function isActive(startTicks: number, durationTicks: number, atTicks: number): boolean {
  return atTicks >= startTicks && atTicks < startTicks + durationTicks;
}

function elementSourceSeconds(element: TimelineElement, atTicks: number): number {
  const speed = Math.max(element.speed_millipercent, 1) / 100_000;
  const elapsedTicks = atTicks - element.start_ticks;
  const sourceTicks = element.source_in_ticks + elapsedTicks * speed;
  return Math.max(0, sourceTicks / TICKS_PER_SECOND);
}

interface WeightedVideoLayer {
  track: TimelineTrack;
  element: TimelineElement;
  /** Opacity multiplier from a transition blend — 1 outside any transition. */
  weight: number;
}

function activeElementsOnTrack(track: TimelineTrack, atTicks: number): TimelineElement[] {
  return track.elements.filter((item) => isActive(item.start_ticks, item.duration_ticks, atTicks));
}

/**
 * Two elements on the same track overlapping in time only happens when a
 * transition was deliberately set up (via ordinary trim/move — there is no
 * "insert an overlapping clip" command). Resolves which element(s) are
 * visible and at what blend weight: `crossfade` shows both at once with
 * complementary weights; `dip_to_black` shows exactly one, fading out to
 * (or in from) nothing rather than ever blending the two pictures together.
 * The effective transition is whichever of the outgoing clip's
 * `transition_out` / the incoming clip's `transition_in` is set (outgoing
 * wins if both are); an overlap with neither configured falls back to "the
 * newer clip wins" rather than a silent double-exposure.
 */
function resolveOverlap(
  track: TimelineTrack,
  active: TimelineElement[],
  atTicks: number,
): WeightedVideoLayer[] {
  if (active.length <= 1) {
    return active.map((element) => ({ track, element, weight: 1 }));
  }
  const [outgoing, incoming] = [...active].sort((a, b) => a.start_ticks - b.start_ticks);
  const transition = outgoing!.transition_out ?? incoming!.transition_in ?? null;
  const overlapStart = incoming!.start_ticks;
  const overlapEnd = outgoing!.start_ticks + outgoing!.duration_ticks;
  if (!transition || overlapEnd <= overlapStart) {
    return [{ track, element: incoming!, weight: 1 }];
  }
  const span = Math.max(1, Math.min(transition.duration_ticks, overlapEnd - overlapStart));
  const windowStart = overlapEnd - span;
  const progress = Math.min(1, Math.max(0, (atTicks - windowStart) / span));
  if (transition.type === 'dip_to_black') {
    return progress < 0.5
      ? [{ track, element: outgoing!, weight: 1 - progress * 2 }]
      : [{ track, element: incoming!, weight: (progress - 0.5) * 2 }];
  }
  return [
    { track, element: outgoing!, weight: 1 - progress },
    { track, element: incoming!, weight: progress },
  ];
}

/**
 * Every visible video layer for a frame — 1 outside a transition, 2 during
 * a crossfade — picked from the topmost non-muted track (`order`
 * descending) that has any active content at `atTicks`. Lower tracks are
 * neither drawn nor heard while a higher one is covering them.
 */
export function activeVideoLayers(document: CanonicalDocument, atTicks: number): WeightedVideoLayer[] {
  const videoTracks = document.tracks
    .filter((track) => track.kind === 'video' && !track.muted)
    .sort((a, b) => b.order - a.order);
  for (const track of videoTracks) {
    const active = activeElementsOnTrack(track, atTicks);
    if (active.length > 0) return resolveOverlap(track, active, atTicks);
  }
  return [];
}

/** The dominant (first) visible video layer — used where only one layer's identity matters, e.g. embedded audio. */
export function activeVideoLayer(
  document: CanonicalDocument,
  atTicks: number,
): { track: TimelineTrack; element: TimelineElement } | undefined {
  return activeVideoLayers(document, atTicks)[0];
}

function buildClipLayer(element: TimelineElement, atTicks: number, weight: number): ActiveClipLayer | null {
  if (!element.asset_id) return null;
  const animations = element.animations;
  const baseOpacity = resolveNumberAtTime(animations, 'opacity', atTicks, 100_000) / 100_000;
  return {
    asset_id: element.asset_id,
    element_id: element.id,
    sourceSeconds: elementSourceSeconds(element, atTicks),
    volume: Math.min(1, Math.max(0, element.volume_millipercent / 100_000)),
    effects: element.effects,
    mask: element.mask,
    opacity: Math.min(1, Math.max(0, baseOpacity * weight)),
    transform: {
      xMilli: resolveNumberAtTime(animations, 'transform.x_milli', atTicks, IDENTITY_TRANSFORM.xMilli),
      yMilli: resolveNumberAtTime(animations, 'transform.y_milli', atTicks, IDENTITY_TRANSFORM.yMilli),
      scaleMillipercent: resolveNumberAtTime(
        animations,
        'transform.scale_millipercent',
        atTicks,
        IDENTITY_TRANSFORM.scaleMillipercent,
      ),
      rotationMillidegrees: resolveNumberAtTime(
        animations,
        'transform.rotation_millidegrees',
        atTicks,
        IDENTITY_TRANSFORM.rotationMillidegrees,
      ),
    },
  };
}

/** Pure timeline resolution — no DOM access, safe to unit test directly. */
export function resolveFrame(document: CanonicalDocument, atTicks: number): FrameLayers {
  const captionTrack = document.tracks.find((track) => track.kind === 'caption');
  const videoLayers = activeVideoLayers(document, atTicks);
  const primary = videoLayers[0];
  const secondary = videoLayers[1];

  const clip = primary ? buildClipLayer(primary.element, atTicks, primary.weight) : null;
  const transitionLayer = secondary ? buildClipLayer(secondary.element, atTicks, secondary.weight) : null;

  const captions = (captionTrack?.elements ?? [])
    .filter(
      (element) => element.text && isActive(element.start_ticks, element.duration_ticks, atTicks),
    )
    .map((element) => element.text as string);

  return {
    canvasWidth: document.canvas.width,
    canvasHeight: document.canvas.height,
    clip,
    transitionLayer,
    captions,
    overlay: document.brand_overlay,
  };
}

function toAudioLayer(
  element: TimelineElement,
  trackId: string,
  atTicks: number,
): ActiveAudioLayer {
  return {
    asset_id: element.asset_id as string,
    element_id: element.id,
    track_id: trackId,
    sourceSeconds: elementSourceSeconds(element, atTicks),
    volume: Math.min(1, Math.max(0, element.volume_millipercent / 100_000)),
    speedFactor: Math.max(element.speed_millipercent, 1) / 100_000,
  };
}

/**
 * Every element that should be audible at `atTicks`: one per non-muted
 * audio track (each track mixes independently — audio has no "topmost"
 * concept, unlike video), plus the currently *visible* video track's own
 * embedded sound (a hidden/occluded video track's audio stays silent too,
 * matching what the viewer sees). Shared by live preview (`audio-mixer.ts`)
 * and export (`export-runner.ts`) so both mix identically.
 */
export function resolveAudioLayers(
  document: CanonicalDocument,
  atTicks: number,
): ActiveAudioLayer[] {
  const layers: ActiveAudioLayer[] = [];
  const audioTracks = document.tracks.filter((track) => track.kind === 'audio' && !track.muted);
  for (const track of audioTracks) {
    const element = track.elements.find((item) =>
      isActive(item.start_ticks, item.duration_ticks, atTicks),
    );
    if (element?.asset_id) layers.push(toAudioLayer(element, track.id, atTicks));
  }
  const video = activeVideoLayer(document, atTicks);
  if (video?.element.asset_id) {
    layers.push(toAudioLayer(video.element, video.track.id, atTicks));
  }
  return layers;
}

/** Caches per-asset <video>/<img> elements across frames so seeking stays cheap. */
export class MediaPool {
  private readonly videos = new Map<string, HTMLVideoElement>();
  private readonly images = new Map<string, HTMLImageElement>();
  // A fully detached <video> is unreliable in Chrome: loading/seeking can
  // silently stall because the element is outside the render tree. Keeping
  // pooled elements attached (off-screen, not display:none) keeps decode
  // and `seeked` events firing normally.
  private readonly host: HTMLDivElement;
  private scratch: OffscreenCanvas | null = null;
  private effectsScratch: OffscreenCanvas | null = null;
  private wasm: WasmCompositor | null | undefined;
  private wasmDimensions: { width: number; height: number } | null = null;

  constructor() {
    this.host = window.document.createElement('div');
    this.host.style.position = 'fixed';
    this.host.style.width = '1px';
    this.host.style.height = '1px';
    this.host.style.overflow = 'hidden';
    this.host.style.opacity = '0';
    this.host.style.pointerEvents = 'none';
    this.host.setAttribute('aria-hidden', 'true');
    window.document.body.appendChild(this.host);
  }

  video(assetId: string, url: string): HTMLVideoElement {
    let element = this.videos.get(assetId);
    if (!element) {
      element = window.document.createElement('video');
      element.crossOrigin = 'anonymous';
      element.muted = true;
      element.playsInline = true;
      element.preload = 'auto';
      element.src = url;
      this.host.appendChild(element);
      this.videos.set(assetId, element);
    }
    return element;
  }

  image(assetId: string, url: string): HTMLImageElement {
    let element = this.images.get(assetId);
    if (!element) {
      element = new Image();
      element.crossOrigin = 'anonymous';
      element.src = url;
      this.host.appendChild(element);
      this.images.set(assetId, element);
    }
    return element;
  }

  /** Reused scratch surface for cover-fitting a frame before GPU upload / fallback draw. */
  scratchCanvas(width: number, height: number): OffscreenCanvas {
    if (!this.scratch || this.scratch.width !== width || this.scratch.height !== height) {
      this.scratch = new OffscreenCanvas(width, height);
    }
    return this.scratch;
  }

  /** A second scratch buffer for `applyClipEffects`, kept separate from `scratchCanvas` since both can be read from in the same frame. */
  effectsScratchCanvas(width: number, height: number): OffscreenCanvas {
    if (!this.effectsScratch || this.effectsScratch.width !== width || this.effectsScratch.height !== height) {
      this.effectsScratch = new OffscreenCanvas(width, height);
    }
    return this.effectsScratch;
  }

  /**
   * Lazily creates (once) the real OpenCut WASM compositor at the given
   * size, resizing it on later calls if the canvas size changed. Returns
   * null forever after the first failed attempt — no per-frame retry cost.
   */
  async wasmCompositorFor(width: number, height: number): Promise<WasmCompositor | null> {
    if (this.wasm === null) return null;
    if (this.wasm === undefined) {
      this.wasm = await WasmCompositor.create(width, height);
      this.wasmDimensions = this.wasm ? { width, height } : null;
      return this.wasm;
    }
    if (this.wasmDimensions?.width !== width || this.wasmDimensions?.height !== height) {
      this.wasm.resize(width, height);
      this.wasmDimensions = { width, height };
    }
    return this.wasm;
  }

  dispose(): void {
    for (const video of this.videos.values()) {
      video.pause();
      video.removeAttribute('src');
      video.load();
    }
    this.videos.clear();
    this.images.clear();
    this.wasm?.dispose();
    this.host.remove();
  }
}

const SEEK_TIMEOUT_MS = 4_000;

export async function seekVideo(video: HTMLVideoElement, seconds: number): Promise<void> {
  const target = Math.max(0, seconds);
  if (video.readyState >= 2 && Math.abs(video.currentTime - target) < 0.02) return;
  await new Promise<void>((resolve) => {
    let settled = false;
    const finish = () => {
      if (settled) return;
      settled = true;
      video.removeEventListener('seeked', onSeeked);
      video.removeEventListener('error', onError);
      resolve();
    };
    const onSeeked = finish;
    const onError = finish;
    // A stuck load (network failure, unsupported codec, a detached element
    // the browser deprioritized) must never hang the render loop forever —
    // draw whatever frame is available and move on.
    window.setTimeout(finish, SEEK_TIMEOUT_MS);
    video.addEventListener('seeked', onSeeked);
    video.addEventListener('error', onError);
    video.currentTime = target;
  });
}

function waitForImage(image: HTMLImageElement): Promise<void> {
  if (image.complete && image.naturalWidth > 0) return Promise.resolve();
  return new Promise<void>((resolve) => {
    const onDone = () => {
      image.removeEventListener('load', onDone);
      image.removeEventListener('error', onDone);
      resolve();
    };
    image.addEventListener('load', onDone);
    image.addEventListener('error', onDone);
  });
}

function drawCover(
  ctx: Canvas2DContext,
  source: CanvasImageSource,
  sourceWidth: number,
  sourceHeight: number,
  canvasWidth: number,
  canvasHeight: number,
): void {
  if (!sourceWidth || !sourceHeight) return;
  const scale = Math.max(canvasWidth / sourceWidth, canvasHeight / sourceHeight);
  const drawWidth = sourceWidth * scale;
  const drawHeight = sourceHeight * scale;
  const dx = (canvasWidth - drawWidth) / 2;
  const dy = (canvasHeight - drawHeight) / 2;
  ctx.drawImage(source, dx, dy, drawWidth, drawHeight);
}

/**
 * Draws an already-canvas-sized clip frame with its resolved opacity and
 * transform (pan/zoom/rotate) applied. With the identity transform and
 * opacity 1 (no keyframes — the overwhelming default) this is pixel-for-
 * pixel the same as the old unconditional `ctx.drawImage(source, 0, 0, w, h)`.
 */
function drawClipTransformed(
  ctx: Canvas2DContext,
  source: CanvasImageSource,
  canvasWidth: number,
  canvasHeight: number,
  opacity: number,
  transform: ClipTransform,
): void {
  const xOffsetPx = (transform.xMilli / 1000) * canvasWidth;
  const yOffsetPx = (transform.yMilli / 1000) * canvasHeight;
  const scale = transform.scaleMillipercent / 100_000;
  const rotationRadians = (transform.rotationMillidegrees / 1000) * (Math.PI / 180);

  ctx.save();
  ctx.globalAlpha = opacity;
  ctx.translate(canvasWidth / 2 + xOffsetPx, canvasHeight / 2 + yOffsetPx);
  ctx.rotate(rotationRadians);
  ctx.scale(scale, scale);
  ctx.drawImage(source, -canvasWidth / 2, -canvasHeight / 2, canvasWidth, canvasHeight);
  ctx.restore();
}

function drawCaptions(
  ctx: CanvasRenderingContext2D,
  canvasWidth: number,
  canvasHeight: number,
  captions: string[],
): void {
  const text = captions.join(' ');
  if (!text) return;
  const fontSize = Math.max(14, Math.round(canvasHeight * 0.045));
  ctx.font = `600 ${fontSize}px sans-serif`;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  const y = canvasHeight * 0.88;
  const metrics = ctx.measureText(text);
  const paddingX = 16;
  const boxHeight = fontSize * 1.6;
  ctx.fillStyle = 'rgba(0,0,0,0.6)';
  ctx.fillRect(
    canvasWidth / 2 - metrics.width / 2 - paddingX,
    y - boxHeight / 2,
    metrics.width + paddingX * 2,
    boxHeight,
  );
  ctx.fillStyle = '#ffffff';
  ctx.fillText(text, canvasWidth / 2, y);
}

/**
 * Resolves + seeks + draws one frame. Callers own the canvas/ctx lifecycle;
 * this only mutates pixel contents and returns the volume the active clip's
 * audio should play at (null when nothing is playing).
 *
 * The video layer renders through the real OpenCut WASM compositor when
 * it's available (GPU-composited via wgpu), and falls back to a plain
 * Canvas2D draw otherwise — same visible result either way, so callers
 * never need to know which path ran.
 */
/**
 * Renders one already-resolved clip layer onto `ctx`: seek → cover-fit onto
 * a scratch canvas → WASM or Canvas2D render → effects/mask → transformed
 * draw. Shared by the primary clip and, during a crossfade, the second
 * (transition) layer — same pipeline either way, called twice per frame
 * only when a transition is actually blending two pictures together.
 */
async function renderClipLayer(
  ctx: CanvasRenderingContext2D,
  canvasWidth: number,
  canvasHeight: number,
  clip: ActiveClipLayer,
  assets: ResolvedAsset[],
  pool: MediaPool,
): Promise<void> {
  const asset = assets.find((item) => item.asset_id === clip.asset_id);
  if (!asset) return;
  const video = pool.video(asset.asset_id, asset.url);
  await seekVideo(video, clip.sourceSeconds);

  const scratch = pool.scratchCanvas(canvasWidth, canvasHeight);
  const scratchCtx = scratch.getContext('2d');
  if (!scratchCtx) return;
  scratchCtx.clearRect(0, 0, canvasWidth, canvasHeight);
  drawCover(
    scratchCtx,
    video,
    video.videoWidth || canvasWidth,
    video.videoHeight || canvasHeight,
    canvasWidth,
    canvasHeight,
  );

  const wasm = await pool.wasmCompositorFor(canvasWidth, canvasHeight);
  const wasmCanvas = wasm?.canvas ?? null;
  const rendered = wasm && wasmCanvas ? wasm.renderVideoFrame(scratch) : false;
  const renderedSource: CanvasImageSource = rendered && wasmCanvas ? wasmCanvas : scratch;
  const hasEffects = clip.effects.length > 0 || clip.mask;
  const finalSource = hasEffects
    ? applyClipEffects(
        renderedSource,
        canvasWidth,
        canvasHeight,
        clip.effects,
        clip.mask,
        rendered ? wasm : null,
        pool.effectsScratchCanvas(canvasWidth, canvasHeight),
      )
    : renderedSource;
  drawClipTransformed(ctx, finalSource, canvasWidth, canvasHeight, clip.opacity, clip.transform);
}

export async function composeFrame(
  ctx: CanvasRenderingContext2D,
  canvasWidth: number,
  canvasHeight: number,
  document: CanonicalDocument,
  atTicks: number,
  assets: ResolvedAsset[],
  pool: MediaPool,
): Promise<{ layers: FrameLayers; clipVolume: number | null }> {
  const layers = resolveFrame(document, atTicks);
  ctx.fillStyle = '#0b0b0d';
  ctx.fillRect(0, 0, canvasWidth, canvasHeight);

  let clipVolume: number | null = null;
  if (layers.clip) {
    await renderClipLayer(ctx, canvasWidth, canvasHeight, layers.clip, assets, pool);
    clipVolume = layers.clip.volume;
  }
  // Drawn on top of the primary layer with its own resolved (already
  // weight-multiplied) opacity — this is what actually shows a crossfade;
  // dip_to_black never produces a transitionLayer, since it shows only one
  // picture at a time by construction (see `resolveOverlap`).
  if (layers.transitionLayer) {
    await renderClipLayer(ctx, canvasWidth, canvasHeight, layers.transitionLayer, assets, pool);
  }

  if (layers.overlay) {
    const overlayAsset = assets.find((item) => item.asset_id === layers.overlay!.asset_id);
    if (overlayAsset) {
      const image = pool.image(overlayAsset.asset_id, overlayAsset.url);
      await waitForImage(image);
      if (image.naturalWidth > 0) {
        const width = (layers.overlay.width_milli / 1000) * canvasWidth;
        const height = width * (image.naturalHeight / image.naturalWidth);
        const x = (layers.overlay.x_milli / 1000) * canvasWidth;
        const y = (layers.overlay.y_milli / 1000) * canvasHeight;
        ctx.drawImage(image, x, y, width, height);
      }
    }
  }

  if (layers.captions.length) {
    drawCaptions(ctx, canvasWidth, canvasHeight, layers.captions);
  }

  return { layers, clipVolume };
}
