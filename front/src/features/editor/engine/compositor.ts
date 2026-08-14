/**
 * Resolves a CanonicalDocument to the layers active at a given tick, and
 * draws them to a canvas. Shared by the live preview (per animation frame)
 * and the sequential export runner (per encoded frame) so both paths render
 * the same edited content instead of drifting apart.
 */

import { TICKS_PER_SECOND, type BrandOverlay, type CanonicalDocument, type ResolvedAsset } from './ports';
import { WasmCompositor } from './wasm-compositor';

type Canvas2DContext = CanvasRenderingContext2D | OffscreenCanvasRenderingContext2D;

export interface ActiveClipLayer {
  asset_id: string;
  element_id: string;
  sourceSeconds: number;
  volume: number;
}

export interface FrameLayers {
  canvasWidth: number;
  canvasHeight: number;
  clip: ActiveClipLayer | null;
  captions: string[];
  overlay: BrandOverlay | null;
}

function isActive(startTicks: number, durationTicks: number, atTicks: number): boolean {
  return atTicks >= startTicks && atTicks < startTicks + durationTicks;
}

/** Pure timeline resolution — no DOM access, safe to unit test directly. */
export function resolveFrame(document: CanonicalDocument, atTicks: number): FrameLayers {
  const videoTrack = document.tracks.find((track) => track.kind === 'video');
  const captionTrack = document.tracks.find((track) => track.kind === 'caption');

  const clipElement = videoTrack?.elements.find((element) =>
    isActive(element.start_ticks, element.duration_ticks, atTicks),
  );

  let clip: ActiveClipLayer | null = null;
  if (clipElement?.asset_id) {
    const speed = Math.max(clipElement.speed_millipercent, 1) / 100_000;
    const elapsedTicks = atTicks - clipElement.start_ticks;
    const sourceTicks = clipElement.source_in_ticks + elapsedTicks * speed;
    clip = {
      asset_id: clipElement.asset_id,
      element_id: clipElement.id,
      sourceSeconds: Math.max(0, sourceTicks / TICKS_PER_SECOND),
      volume: Math.min(1, Math.max(0, clipElement.volume_millipercent / 100_000)),
    };
  }

  const captions = (captionTrack?.elements ?? [])
    .filter(
      (element) => element.text && isActive(element.start_ticks, element.duration_ticks, atTicks),
    )
    .map((element) => element.text as string);

  return {
    canvasWidth: document.canvas.width,
    canvasHeight: document.canvas.height,
    clip,
    captions,
    overlay: document.brand_overlay,
  };
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
    const asset = assets.find((item) => item.asset_id === layers.clip!.asset_id);
    if (asset) {
      const video = pool.video(asset.asset_id, asset.url);
      await seekVideo(video, layers.clip.sourceSeconds);

      const scratch = pool.scratchCanvas(canvasWidth, canvasHeight);
      const scratchCtx = scratch.getContext('2d');
      if (scratchCtx) {
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
        if (rendered && wasmCanvas) {
          ctx.drawImage(wasmCanvas, 0, 0, canvasWidth, canvasHeight);
        } else {
          ctx.drawImage(scratch, 0, 0);
        }
      }
      clipVolume = layers.clip.volume;
    }
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
