/**
 * Applies a clip's effects and mask to its already-rendered frame — the
 * WASM compositor's own canvas, or the plain Canvas2D scratch draw when
 * WASM isn't available. Runs after `resolveFrame`, before the result is
 * drawn onto the caller's visible/export canvas, so effects/masks look
 * identical regardless of which renderer drew the underlying picture.
 */

import type { ClipEffect, ClipMask } from './ports';
import type { WasmCompositor } from './wasm-compositor';

const BLUR_INTENSITY_DIVISOR = 5;
const BLUR_REFERENCE_WIDTH = 1920;
const BLUR_REFERENCE_HEIGHT = 1080;
/** Rough px-per-intensity-unit match to the WASM path's sigma scale, for the no-WASM fallback. */
const BLUR_FALLBACK_PX_DIVISOR = 3;

function intensityToSigma(intensity: number, resolution: number, reference: number): number {
  return Math.max((intensity / BLUR_INTENSITY_DIVISOR) * (resolution / reference), 0.001);
}

function clampPercent(value: number, min = 0, max = 400): number {
  return Math.min(max, Math.max(min, value));
}

function toOffscreenCanvas(
  source: CanvasImageSource,
  width: number,
  height: number,
  scratch: OffscreenCanvas,
): OffscreenCanvas {
  if (source instanceof OffscreenCanvas && source.width === width && source.height === height) {
    return source;
  }
  const ctx = scratch.getContext('2d');
  if (!ctx) return scratch;
  ctx.clearRect(0, 0, width, height);
  ctx.drawImage(source, 0, 0, width, height);
  return scratch;
}

/**
 * Builds the CSS filter string for every non-blur effect, plus blur itself
 * when no GPU pass ran for it (WASM unavailable) — `ctx.filter` blur is a
 * reasonable single-pass approximation of the real Gaussian shader.
 */
function cssFilterFor(effects: ClipEffect[], includeBlurFallback: boolean): string {
  const parts: string[] = [];
  for (const effect of effects) {
    const amount = effect.params.amount ?? 100;
    switch (effect.type) {
      case 'brightness':
        parts.push(`brightness(${clampPercent(amount)}%)`);
        break;
      case 'contrast':
        parts.push(`contrast(${clampPercent(amount)}%)`);
        break;
      case 'saturate':
        parts.push(`saturate(${clampPercent(amount)}%)`);
        break;
      case 'grayscale':
        parts.push(`grayscale(${clampPercent(amount, 0, 100)}%)`);
        break;
      case 'blur':
        if (includeBlurFallback) {
          const intensity = effect.params.intensity ?? 15;
          parts.push(`blur(${Math.max(0, Math.round(intensity / BLUR_FALLBACK_PX_DIVISOR))}px)`);
        }
        break;
    }
  }
  return parts.join(' ');
}

function drawMaskShape(ctx: OffscreenCanvasRenderingContext2D, mask: ClipMask, width: number, height: number): void {
  const x = (mask.x_milli / 1000) * width;
  const y = (mask.y_milli / 1000) * height;
  const w = (mask.width_milli / 1000) * width;
  const h = (mask.height_milli / 1000) * height;
  ctx.fillStyle = '#ffffff';
  if (mask.shape === 'ellipse') {
    ctx.beginPath();
    ctx.ellipse(x + w / 2, y + h / 2, Math.abs(w / 2), Math.abs(h / 2), 0, 0, Math.PI * 2);
    ctx.fill();
  } else {
    ctx.fillRect(x, y, w, h);
  }
}

function applyMask(
  source: CanvasImageSource,
  width: number,
  height: number,
  mask: ClipMask,
): OffscreenCanvas {
  const featherPx = Math.max(0, (mask.feather_millipercent / 100_000) * height);
  const maskCanvas = new OffscreenCanvas(width, height);
  const maskCtx = maskCanvas.getContext('2d');
  if (maskCtx) {
    // Feathering the alpha-bearing shape itself (transparent background,
    // opaque white shape) via a CSS blur is what makes `destination-in`
    // below fade smoothly instead of cutting a hard edge — this is
    // Canvas2D-only and deliberately doesn't route through the vendored
    // WASM `applyMaskFeather` (confirmed working, see the effects spike),
    // since that call feathers luminance rather than alpha and would need
    // a per-frame CPU readback to convert into something `destination-in`
    // can use — not worth the frame-rate risk for a soft-edge mask.
    if (featherPx > 0) maskCtx.filter = `blur(${featherPx}px)`;
    drawMaskShape(maskCtx, mask, width, height);
    maskCtx.filter = 'none';
  }

  const output = new OffscreenCanvas(width, height);
  const outCtx = output.getContext('2d');
  if (!outCtx) return output;
  outCtx.drawImage(source, 0, 0, width, height);
  outCtx.globalCompositeOperation = 'destination-in';
  outCtx.drawImage(maskCanvas, 0, 0);
  outCtx.globalCompositeOperation = 'source-over';
  return output;
}

export function applyClipEffects(
  source: CanvasImageSource,
  width: number,
  height: number,
  effects: ClipEffect[],
  mask: ClipMask | null,
  wasm: WasmCompositor | null,
  scratch: OffscreenCanvas,
): CanvasImageSource {
  if (effects.length === 0 && !mask) return source;

  let current: CanvasImageSource = source;

  const blurEffect = effects.find((effect) => effect.type === 'blur');
  let blurredByWasm = false;
  if (blurEffect && wasm) {
    const intensity = blurEffect.params.intensity ?? 15;
    const sigmaX = intensityToSigma(intensity, width, BLUR_REFERENCE_WIDTH);
    const sigmaY = intensityToSigma(intensity, height, BLUR_REFERENCE_HEIGHT);
    const blurred = wasm.applyBlur(toOffscreenCanvas(current, width, height, scratch), sigmaX, sigmaY);
    if (blurred) {
      current = blurred;
      blurredByWasm = true;
    }
  }

  const filter = cssFilterFor(effects, !blurredByWasm);
  if (filter) {
    const filterCanvas = new OffscreenCanvas(width, height);
    const ctx = filterCanvas.getContext('2d');
    if (ctx) {
      ctx.filter = filter;
      ctx.drawImage(current, 0, 0, width, height);
      ctx.filter = 'none';
      current = filterCanvas;
    }
  }

  if (mask) {
    current = applyMask(current, width, height, mask);
  }

  return current;
}
