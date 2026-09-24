import type { BlockingDocument } from '../types';

/**
 * Renders one blockout segment to an MP4 in the browser — the reference
 * video a generation job receives as its motion guide.
 *
 * Uses the same `BlockingPlayer` (and therefore the same compiled timeline)
 * as the studio viewport, on a detached canvas with guides and labels off:
 * frame *n* is `renderAt(segment.start + n / fps)`, deterministic, so the
 * clip matches what the author watched frame for frame. Encoding is
 * mediabunny's WebCodecs H.264 path, as `features/editor/engine/
 * export-runner.ts` does for timeline exports; both modules are loaded
 * lazily so the studio page itself stays light.
 */

export const EXPORT_FPS = 24;

const EXPORT_SIZE: Record<BlockingDocument['aspect_ratio'], { width: number; height: number }> = {
  '9:16': { width: 720, height: 1280 },
  '16:9': { width: 1280, height: 720 },
  '1:1': { width: 960, height: 960 },
};

export interface RenderProgress {
  /** 0–1 within this segment. */
  fraction: number;
}

export async function renderSegmentToMp4(
  document: BlockingDocument,
  segmentKey: string,
  options: { signal?: AbortSignal; onProgress?: (progress: RenderProgress) => void } = {},
): Promise<Blob> {
  // Destructured straight off `await import(...)`, like `export-runner.ts`:
  // holding the module namespace in a variable (e.g. through `Promise.all`)
  // stops the bundler tree-shaking mediabunny and more than doubles its chunk.
  const { BlockingPlayer } = await import('../engine/player');
  const { BufferTarget, CanvasSource, Mp4OutputFormat, Output, QUALITY_MEDIUM } =
    await import('mediabunny');
  const size = EXPORT_SIZE[document.aspect_ratio];
  const canvas = window.document.createElement('canvas');
  canvas.width = size.width;
  canvas.height = size.height;

  const player = new BlockingPlayer({ canvas, interactive: false, pixelRatio: 1 });
  try {
    player.setSize(size.width, size.height);
    player.setGuides(false);
    player.setDocument(document);
    const segment = player.timeline?.segments.find((item) => item.key === segmentKey);
    if (!segment) throw new Error(`segment_not_found:${segmentKey}`);

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
    return new Blob([buffer], { type: 'video/mp4' });
  } finally {
    player.dispose();
  }
}

/** The file name the upload carries — informative in the asset library. */
export function segmentClipName(segmentKey: string): string {
  const safe = segmentKey.replace(/[^\p{L}\p{N}#_-]+/gu, '_').slice(0, 60);
  return `blocking_${safe}.mp4`;
}
