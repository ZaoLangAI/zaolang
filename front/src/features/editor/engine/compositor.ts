/**
 * Resolves a CanonicalDocument to the layers active at a given tick, and
 * draws them to a canvas. Shared by the live preview (per animation frame)
 * and the sequential export runner (per encoded frame) so both paths render
 * the same edited content instead of drifting apart.
 */

import { resolveNumberAtTime } from './animation';
import { type CaptionLayout, layoutCaptionLines } from './caption-layout';
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
  /** Playback-rate multiplier from `speed_millipercent` — drives `<video>.playbackRate` while previewing in play mode. */
  speedFactor: number;
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
  const resolvedVolume = resolveNumberAtTime(animations, 'volume', atTicks, element.volume_millipercent);
  return {
    asset_id: element.asset_id,
    element_id: element.id,
    sourceSeconds: elementSourceSeconds(element, atTicks),
    volume: Math.min(1, Math.max(0, resolvedVolume / 100_000)),
    effects: element.effects,
    mask: element.mask,
    opacity: Math.min(1, Math.max(0, baseOpacity * weight)),
    speedFactor: Math.max(element.speed_millipercent, 1) / 100_000,
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
  const resolvedVolume = resolveNumberAtTime(
    element.animations,
    'volume',
    atTicks,
    element.volume_millipercent,
  );
  return {
    asset_id: element.asset_id as string,
    element_id: element.id,
    track_id: trackId,
    sourceSeconds: elementSourceSeconds(element, atTicks),
    volume: Math.min(1, Math.max(0, resolvedVolume / 100_000)),
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
  private scratchTainted = false;
  private effectsScratch: OffscreenCanvas | null = null;
  private frame: OffscreenCanvas | null = null;
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
    if (
      !this.scratch ||
      this.scratch.width !== width ||
      this.scratch.height !== height ||
      this.scratchTainted
    ) {
      this.scratch = new OffscreenCanvas(width, height);
      this.scratchTainted = false;
    }
    return this.scratch;
  }

  /**
   * A canvas's "origin-clean" flag can only ever go from clean to tainted,
   * never back — once a cross-origin draw taints `scratch` (e.g. a stale
   * cache entry or transient CORS failure on the source video), every later
   * frame reusing the same instance would stay poisoned forever. Call this
   * when tainting is detected so the next `scratchCanvas()` call replaces it
   * with a fresh one instead of compounding the failure across the session.
   */
  markScratchTainted(): void {
    this.scratchTainted = true;
    // The tainted scratch gets drawn onto the frame buffer too; drop it so
    // the next frame starts from a clean surface as well.
    this.frame = null;
  }

  /**
   * Off-screen surface a whole frame is composed on before being blitted to
   * the visible canvas in one `drawImage`. Composing directly on the visible
   * canvas showed its cleared background for the whole duration of the
   * clip's seek/decode await — i.e. a black preview for most of playback.
   */
  frameCanvas(width: number, height: number): OffscreenCanvas {
    if (!this.frame || this.frame.width !== width || this.frame.height !== height) {
      this.frame = new OffscreenCanvas(width, height);
    }
    return this.frame;
  }

  /**
   * Play mode: keep exactly the given assets' `<video>` elements running and
   * pause every other pooled one, so a clip that just left the playhead
   * doesn't keep decoding (and drifting) in the background.
   */
  keepPlaying(assetIds: ReadonlySet<string>): void {
    for (const [assetId, video] of this.videos) {
      if (!assetIds.has(assetId) && !video.paused) video.pause();
    }
  }

  pauseAll(): void {
    this.keepPlaying(new Set());
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

/**
 * Beyond this the element's own clock and the editor playhead have visibly
 * parted ways (a dropped rAF burst, a tab switch, ...) and a hard re-seek is
 * cheaper than the stutter; under it the two are left to free-run, since
 * seeking every frame is exactly what made playback a black flicker.
 */
const PLAYBACK_DRIFT_SECONDS = 0.2;
const MIN_PLAYBACK_RATE = 0.0625;
const MAX_PLAYBACK_RATE = 16;

/**
 * Play mode: instead of seeking a paused `<video>` to every frame (each seek
 * is a decode round-trip that leaves the element with no current frame for
 * tens of milliseconds), let the element *play* at the clip's speed and only
 * nudge it back on drift. Whatever frame it has right now is what gets drawn.
 */
function syncPlayingVideo(video: HTMLVideoElement, seconds: number, speedFactor: number): void {
  const target = Math.max(0, seconds);
  const rate = Math.min(MAX_PLAYBACK_RATE, Math.max(MIN_PLAYBACK_RATE, speedFactor));
  if (video.playbackRate !== rate) video.playbackRate = rate;
  if (!video.seeking && Math.abs(video.currentTime - target) > PLAYBACK_DRIFT_SECONDS) {
    video.currentTime = target;
  }
  // Past the source's end there is nothing more to play — calling `play()`
  // on an ended element would loop it back to 0.
  const beyondEnd = Number.isFinite(video.duration) && target >= video.duration;
  if (video.paused && !beyondEnd && video.readyState >= 1) {
    // Autoplay policy permits muted playback without a gesture; a rejection
    // here just means this frame draws whatever was last decoded.
    void video.play().catch(() => undefined);
  }
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

// Export draws the same caption every frame for seconds at a time; laying it
// out once per (text, size, width) keeps `measureText` off the hot path.
const captionLayoutCache = new Map<string, CaptionLayout>();
const CAPTION_LAYOUT_CACHE_LIMIT = 256;

function captionLayout(
  ctx: Canvas2DContext,
  text: string,
  baseFontSize: number,
  maxWidth: number,
  maxLines: number,
): CaptionLayout {
  const key = `${baseFontSize}|${Math.round(maxWidth)}|${maxLines}|${text}`;
  const cached = captionLayoutCache.get(key);
  if (cached) return cached;
  const layout = layoutCaptionLines(
    text,
    maxWidth,
    (value, scale) => {
      ctx.font = `600 ${Math.round(baseFontSize * scale)}px sans-serif`;
      return ctx.measureText(value).width;
    },
    maxLines,
  );
  if (captionLayoutCache.size >= CAPTION_LAYOUT_CACHE_LIMIT) captionLayoutCache.clear();
  captionLayoutCache.set(key, layout);
  return layout;
}

/**
 * Bottom-anchored caption block: wrapped to at most two lines (more only
 * when several captions show at once), shrunk then ellipsized rather than
 * ever running off the frame — see `caption-layout.ts`. The last line keeps
 * its old 0.88h position so single-line captions sit exactly where they did.
 */
function drawCaptions(
  ctx: Canvas2DContext,
  canvasWidth: number,
  canvasHeight: number,
  captions: string[],
): void {
  const paragraphs = captions.map((caption) => caption.trim()).filter(Boolean);
  if (paragraphs.length === 0) return;
  const baseFontSize = Math.max(14, Math.round(canvasHeight * 0.045));
  const paddingX = 16;
  const maxWidth = canvasWidth * 0.9 - paddingX * 2;
  const layout = captionLayout(
    ctx,
    paragraphs.join('\n'),
    baseFontSize,
    maxWidth,
    Math.max(2, paragraphs.length),
  );
  if (layout.lines.length === 0) return;

  const fontSize = Math.round(baseFontSize * layout.fontScale);
  ctx.font = `600 ${fontSize}px sans-serif`;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  const lineHeight = fontSize * 1.3;
  const boxHeight = fontSize * 1.6;
  const lastY = canvasHeight * 0.88;
  const firstY = lastY - (layout.lines.length - 1) * lineHeight;
  const widest = Math.max(...layout.lines.map((line) => ctx.measureText(line).width));
  ctx.fillStyle = 'rgba(0,0,0,0.6)';
  ctx.fillRect(
    canvasWidth / 2 - widest / 2 - paddingX,
    firstY - boxHeight / 2,
    widest + paddingX * 2,
    lastY - firstY + boxHeight,
  );
  ctx.fillStyle = '#ffffff';
  layout.lines.forEach((line, index) => {
    ctx.fillText(line, canvasWidth / 2, firstY + index * lineHeight);
  });
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
  ctx: Canvas2DContext,
  canvasWidth: number,
  canvasHeight: number,
  clip: ActiveClipLayer,
  assets: ResolvedAsset[],
  pool: MediaPool,
  playing: boolean,
): Promise<boolean> {
  const asset = assets.find((item) => item.asset_id === clip.asset_id);
  if (!asset) return true;
  const video = pool.video(asset.asset_id, asset.url);
  try {
    if (playing) {
      syncPlayingVideo(video, clip.sourceSeconds, clip.speedFactor);
    } else {
      if (!video.paused) video.pause();
      await seekVideo(video, clip.sourceSeconds);
    }

    // A video that hasn't buffered an actual frame yet (readyState still
    // HAVE_NOTHING/HAVE_METADATA — a stalled network fetch, a seek that
    // timed out in `seekVideo`, a play-mode drift correction still in
    // flight, ...) makes `drawImage` throw InvalidStateError rather than
    // silently no-op. Report "no picture" so the caller can decide whether
    // to show the blank or hold the previous frame.
    if (video.readyState < 2 || video.seeking) return false;

    const scratch = pool.scratchCanvas(canvasWidth, canvasHeight);
    const scratchCtx = scratch.getContext('2d');
    if (!scratchCtx) return false;
    scratchCtx.clearRect(0, 0, canvasWidth, canvasHeight);
    drawCover(
      scratchCtx,
      video,
      video.videoWidth || canvasWidth,
      video.videoHeight || canvasHeight,
      canvasWidth,
      canvasHeight,
    );

    // A cross-origin source that fails strict CORS validation (stale cache
    // entry from a non-crossOrigin request to the same URL elsewhere, a
    // misconfigured bucket, a mid-flight signed-URL expiry, ...) taints this
    // canvas. Reading it back throws synchronously and cheaply here, whereas
    // the WASM compositor's GPU texture upload can fail on a tainted source
    // *asynchronously* in a way no try/catch around it can observe — and
    // once that happens the WASM module's internal state is unrecoverable
    // for the rest of the session. Detecting the taint ourselves first means
    // the GPU path is simply skipped for this one frame (Canvas2D still
    // draws a tainted source onto another canvas just fine) instead of ever
    // risking that crash.
    let tainted = false;
    try {
      scratchCtx.getImageData(0, 0, 1, 1);
    } catch {
      tainted = true;
      pool.markScratchTainted();
    }

    const wasm = tainted ? null : await pool.wasmCompositorFor(canvasWidth, canvasHeight);
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
    return true;
  } catch (error) {
    // Never let one bad frame (stalled decode, an unexpected GPU error,
    // ...) throw out of the render loop — the caller already cleared the
    // canvas to the background color, so worst case this frame's clip area
    // stays blank instead of freezing/crashing the whole preview.
    console.error('[editor] renderClipLayer failed, skipping this frame', error);
    return false;
  }
}

export function aiLabelFontSize(canvasHeight: number): number {
  return Math.max(12, Math.round(canvasHeight * 0.028));
}

/**
 * Where the visible "AI 生成" label sits: a pill in the top-right corner (the
 * brand overlay defaults to the top-left), sized from the frame height so it
 * reads the same at every export resolution and never leaves the frame.
 */
export function aiLabelRect(
  canvasWidth: number,
  canvasHeight: number,
  textWidth: number,
): { x: number; y: number; width: number; height: number; paddingX: number } {
  const fontSize = aiLabelFontSize(canvasHeight);
  const paddingX = Math.round(fontSize * 0.6);
  const margin = Math.round(Math.min(canvasWidth, canvasHeight) * 0.03);
  const width = Math.min(textWidth + paddingX * 2, canvasWidth - margin * 2);
  const height = Math.round(fontSize * 1.6);
  return { x: canvasWidth - margin - width, y: margin, width, height, paddingX };
}

function drawAiLabel(
  ctx: Canvas2DContext,
  canvasWidth: number,
  canvasHeight: number,
  text: string,
): void {
  if (!text) return;
  ctx.save();
  ctx.font = `600 ${aiLabelFontSize(canvasHeight)}px sans-serif`;
  const rect = aiLabelRect(canvasWidth, canvasHeight, ctx.measureText(text).width);
  ctx.fillStyle = 'rgba(0,0,0,0.55)';
  ctx.fillRect(rect.x, rect.y, rect.width, rect.height);
  ctx.fillStyle = '#ffffff';
  ctx.textAlign = 'left';
  ctx.textBaseline = 'middle';
  ctx.fillText(text, rect.x + rect.paddingX, rect.y + rect.height / 2);
  ctx.restore();
}

export interface ComposeFrameOptions {
  /**
   * Live playback: the active clips' `<video>` elements free-run at clip
   * speed and the frame draws whatever they currently hold, instead of the
   * exact-seek-per-frame path that scrubbing and export rely on.
   */
  playing?: boolean;
  /**
   * Export-only visible "AI 生成" stamp (`ExportRenderOptions.aiLabel`),
   * drawn last so no layer covers it.
   */
  aiLabel?: { text: string };
}

export async function composeFrame(
  target: CanvasRenderingContext2D,
  canvasWidth: number,
  canvasHeight: number,
  document: CanonicalDocument,
  atTicks: number,
  assets: ResolvedAsset[],
  pool: MediaPool,
  options: ComposeFrameOptions = {},
): Promise<{ layers: FrameLayers; clipVolume: number | null }> {
  const playing = options.playing === true;
  const layers = resolveFrame(document, atTicks);

  // Compose off-screen, blit once at the end: the visible canvas never shows
  // the half-built (background-only) state while a clip is still seeking.
  const frame = pool.frameCanvas(canvasWidth, canvasHeight);
  const ctx = frame.getContext('2d');
  if (!ctx) return { layers, clipVolume: null };
  ctx.fillStyle = '#0b0b0d';
  ctx.fillRect(0, 0, canvasWidth, canvasHeight);

  if (playing) {
    const active = new Set<string>();
    if (layers.clip) active.add(layers.clip.asset_id);
    if (layers.transitionLayer) active.add(layers.transitionLayer.asset_id);
    pool.keepPlaying(active);
  } else {
    pool.pauseAll();
  }

  let clipVolume: number | null = null;
  let complete = true;
  if (layers.clip) {
    complete = await renderClipLayer(ctx, canvasWidth, canvasHeight, layers.clip, assets, pool, playing);
    clipVolume = layers.clip.volume;
  }
  // Drawn on top of the primary layer with its own resolved (already
  // weight-multiplied) opacity — this is what actually shows a crossfade;
  // dip_to_black never produces a transitionLayer, since it shows only one
  // picture at a time by construction (see `resolveOverlap`).
  if (layers.transitionLayer) {
    const drew = await renderClipLayer(
      ctx,
      canvasWidth,
      canvasHeight,
      layers.transitionLayer,
      assets,
      pool,
      playing,
    );
    complete = complete && drew;
  }
  // Play mode only: a clip whose element is mid-seek (it just entered the
  // playhead, or a drift correction is in flight) has no frame to give yet.
  // Holding the last presented frame for those few milliseconds beats
  // flashing the background; scrubbing and export always present, since
  // they waited for the seek and a blank there is real information.
  if (playing && !complete) return { layers, clipVolume };

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

  if (options.aiLabel) {
    drawAiLabel(ctx, canvasWidth, canvasHeight, options.aiLabel.text);
  }

  target.drawImage(frame, 0, 0, canvasWidth, canvasHeight);
  return { layers, clipVolume };
}
