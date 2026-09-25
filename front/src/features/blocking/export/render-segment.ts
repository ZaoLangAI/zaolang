import type { BlockingDocument } from '../types';

/**
 * Renders one blockout segment to a video file in the browser — the
 * reference clip a generation job receives as its motion guide.
 *
 * Uses the same `BlockingPlayer` (and therefore the same compiled timeline)
 * as the studio viewport, on a detached canvas with guides and labels off:
 * frame *n* is `renderAt(segment.start + n / fps)`, so the clip matches what
 * the author watched.
 *
 * Two encoders, best first:
 * - **WebCodecs** (mediabunny's H.264 path, as `features/editor/engine/
 *   export-runner.ts` does): frame-exact and faster than real time. Browsers
 *   only expose `VideoEncoder` in a *secure context* — HTTPS or localhost —
 *   so a site served over plain HTTP never has it, whatever the browser.
 * - **MediaRecorder** on the canvas stream: available over plain HTTP too.
 *   It records in real time (a 10s segment takes ~10s) and prefers MP4
 *   (Chrome 126+, Safari), falling back to WebM (Firefox); uploads accept
 *   both.
 */

export const EXPORT_FPS = 24;

const EXPORT_SIZE: Record<BlockingDocument['aspect_ratio'], { width: number; height: number }> = {
  '9:16': { width: 720, height: 1280 },
  '16:9': { width: 1280, height: 720 },
  '1:1': { width: 960, height: 960 },
};

/** MediaRecorder formats in preference order; the upload's mime type is
 * the part before `;` (the upload allow-list matches it exactly). */
const RECORDER_TYPES = [
  'video/mp4;codecs=avc1',
  'video/mp4',
  'video/webm;codecs=vp9',
  'video/webm;codecs=vp8',
  'video/webm',
] as const;

const RECORDER_BITRATE = 6_000_000;

export interface RenderProgress {
  /** 0–1 within this segment. */
  fraction: number;
}

export interface RenderedClip {
  blob: Blob;
  /** `video/mp4` or `video/webm`, without codec parameters. */
  mimeType: 'video/mp4' | 'video/webm';
  extension: 'mp4' | 'webm';
}

type RenderOptions = {
  signal?: AbortSignal;
  onProgress?: (progress: RenderProgress) => void;
};

export class BrowserCannotEncodeError extends Error {
  constructor() {
    super('browser_cannot_encode_video');
    this.name = 'BrowserCannotEncodeError';
  }
}

function webCodecsAvailable(): boolean {
  return typeof window !== 'undefined' && 'VideoEncoder' in window && window.isSecureContext;
}

export function recorderMimeType(
  isTypeSupported: (type: string) => boolean = (type) =>
    typeof MediaRecorder !== 'undefined' && MediaRecorder.isTypeSupported(type),
): (typeof RECORDER_TYPES)[number] | null {
  return RECORDER_TYPES.find((type) => isTypeSupported(type)) ?? null;
}

/** Whether this browser can render a segment at all (for disabling the
 * button up front rather than failing after a credit quote). */
export function canRenderClips(): boolean {
  return webCodecsAvailable() || recorderMimeType() !== null;
}

async function setUp(document: BlockingDocument, segmentKey: string) {
  const { BlockingPlayer } = await import('../engine/player');
  const size = EXPORT_SIZE[document.aspect_ratio];
  const canvas = window.document.createElement('canvas');
  canvas.width = size.width;
  canvas.height = size.height;
  const player = new BlockingPlayer({ canvas, interactive: false, pixelRatio: 1 });
  player.setSize(size.width, size.height);
  player.setGuides(false);
  player.setDocument(document);
  const segment = player.timeline?.segments.find((item) => item.key === segmentKey);
  if (!segment) {
    player.dispose();
    throw new Error(`segment_not_found:${segmentKey}`);
  }
  return { canvas, player, segment };
}

async function renderWithWebCodecs(
  document: BlockingDocument,
  segmentKey: string,
  options: RenderOptions,
): Promise<RenderedClip> {
  // Destructured straight off `await import(...)`, like `export-runner.ts`:
  // holding the module namespace in a variable stops the bundler
  // tree-shaking mediabunny and more than doubles its chunk.
  const { BufferTarget, CanvasSource, Mp4OutputFormat, Output, QUALITY_MEDIUM } =
    await import('mediabunny');
  const { canvas, player, segment } = await setUp(document, segmentKey);
  try {
    const target = new BufferTarget();
    const output = new Output({ format: new Mp4OutputFormat(), target });
    const source = new CanvasSource(canvas, { codec: 'avc', bitrate: QUALITY_MEDIUM });
    output.addVideoTrack(source, { frameRate: EXPORT_FPS });
    await output.start();

    const frames = Math.max(1, Math.round(segment.duration * EXPORT_FPS));
    for (let index = 0; index < frames; index += 1) {
      if (options.signal?.aborted) {
        await output.cancel();
        throw new DOMException('Aborted', 'AbortError');
      }
      player.renderAt(segment.start + index / EXPORT_FPS);
      await source.add(index / EXPORT_FPS, 1 / EXPORT_FPS);
      if (index % 12 === 0) options.onProgress?.({ fraction: index / frames });
    }
    source.close();
    await output.finalize();
    options.onProgress?.({ fraction: 1 });
    const buffer = target.buffer;
    if (!buffer) throw new Error('empty_export');
    return {
      blob: new Blob([buffer], { type: 'video/mp4' }),
      mimeType: 'video/mp4',
      extension: 'mp4',
    };
  } finally {
    player.dispose();
  }
}

const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

async function renderWithRecorder(
  document: BlockingDocument,
  segmentKey: string,
  options: RenderOptions,
): Promise<RenderedClip> {
  const recorderType = recorderMimeType();
  if (!recorderType) throw new BrowserCannotEncodeError();
  const mimeType = recorderType.startsWith('video/mp4') ? 'video/mp4' : 'video/webm';
  const { canvas, player, segment } = await setUp(document, segmentKey);

  // Some engines only stream frames from a canvas that is in the document;
  // keep it attached but invisible for the duration of the recording.
  canvas.style.cssText = 'position:fixed;left:-10000px;top:0;pointer-events:none;opacity:0';
  window.document.body.appendChild(canvas);
  const stream = canvas.captureStream(EXPORT_FPS);
  const recorder = new MediaRecorder(stream, {
    mimeType: recorderType,
    videoBitsPerSecond: RECORDER_BITRATE,
  });
  const chunks: Blob[] = [];
  recorder.addEventListener('dataavailable', (event) => {
    if (event.data.size > 0) chunks.push(event.data);
  });
  const stopped = new Promise<void>((resolve) =>
    recorder.addEventListener('stop', () => resolve(), { once: true }),
  );

  try {
    player.renderAt(segment.start);
    recorder.start(250);
    // Real time: frame n goes up at start + n/fps of wall clock, so the
    // recorder's own timestamps give the clip its true length.
    const frames = Math.max(1, Math.round(segment.duration * EXPORT_FPS));
    const began = performance.now();
    for (let index = 0; index < frames; index += 1) {
      if (options.signal?.aborted) throw new DOMException('Aborted', 'AbortError');
      player.renderAt(segment.start + index / EXPORT_FPS);
      if (index % 12 === 0) options.onProgress?.({ fraction: index / frames });
      const due = began + ((index + 1) * 1000) / EXPORT_FPS;
      await sleep(Math.max(0, due - performance.now()));
    }
    recorder.stop();
    await stopped;
    options.onProgress?.({ fraction: 1 });
    if (chunks.length === 0) throw new Error('empty_export');
    return {
      blob: new Blob(chunks, { type: mimeType }),
      mimeType,
      extension: mimeType === 'video/mp4' ? 'mp4' : 'webm',
    };
  } finally {
    if (recorder.state !== 'inactive') recorder.stop();
    stream.getTracks().forEach((track) => track.stop());
    canvas.remove();
    player.dispose();
  }
}

export async function renderSegmentClip(
  document: BlockingDocument,
  segmentKey: string,
  options: RenderOptions = {},
): Promise<RenderedClip> {
  if (webCodecsAvailable()) {
    try {
      return await renderWithWebCodecs(document, segmentKey, options);
    } catch (error) {
      // An encoder that exists but cannot do H.264 at this size (some
      // Firefox builds) should not fail the job when recording would work.
      if (error instanceof DOMException && error.name === 'AbortError') throw error;
      if (recorderMimeType() === null) throw error;
    }
  }
  return renderWithRecorder(document, segmentKey, options);
}

/** The file name the upload carries — informative in the asset library. */
export function segmentClipName(segmentKey: string, extension: 'mp4' | 'webm' = 'mp4'): string {
  const safe = segmentKey.replace(/[^\p{L}\p{N}#_-]+/gu, '_').slice(0, 60);
  return `blocking_${safe}.${extension}`;
}
