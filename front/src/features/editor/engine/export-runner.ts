import { composeFrame, MediaPool } from './compositor';
import {
  EXPORT_MAX_DURATION_TICKS,
  EXPORT_MAX_ESTIMATED_BYTES,
  EXPORT_MAX_PIXELS,
  TICKS_PER_SECOND,
  type CanonicalDocument,
  type CapabilityReport,
  type ExportProgress,
  type RendererBackend,
  type ResolvedAsset,
  type VariantSpec,
} from './ports';

/**
 * Sequential browser export. Renders the same edited timeline the preview
 * shows (via `compositor.ts`) frame by frame into a canvas, then encodes it
 * with mediabunny. Classic BufferTarget holds the file in memory, so product
 * hard limits (30s / 1080p / 80MB estimate) are the stop-gate until a
 * streaming encoder lands. Audio is not yet encoded — this pass only fixes
 * the picture track matching the edited document.
 */
export class SequentialExportRunner implements RendererBackend {
  async preflight(spec: VariantSpec): Promise<CapabilityReport> {
    const reasons: string[] = [];
    const pixels = spec.width * spec.height;
    if (pixels > EXPORT_MAX_PIXELS) reasons.push('resolution');
    if (spec.max_duration_ticks > EXPORT_MAX_DURATION_TICKS) reasons.push('duration');
    const chrome = /Chrome|Edg\//.test(navigator.userAgent) && !/Mobile/.test(navigator.userAgent);
    if (!chrome) reasons.push('browser');
    const estimated = Math.ceil((spec.max_duration_ticks / TICKS_PER_SECOND) * pixels * 0.12);
    if (estimated > EXPORT_MAX_ESTIMATED_BYTES) reasons.push('memory');
    if (typeof VideoEncoder === 'undefined') reasons.push('webcodecs');
    return { ok: reasons.length === 0, reasons, estimated_bytes: estimated };
  }

  async *export(
    spec: VariantSpec,
    document: CanonicalDocument,
    assets: ResolvedAsset[],
    signal: AbortSignal,
  ): AsyncIterable<ExportProgress> {
    const report = await this.preflight(spec);
    if (!report.ok) {
      throw new Error(`export_preflight:${report.reasons.join(',')}`);
    }

    const canvas = window.document.createElement('canvas');
    canvas.width = Math.min(spec.width, 1280);
    canvas.height = Math.min(spec.height, 720);
    const ctx = canvas.getContext('2d');
    if (!ctx) throw new Error('canvas');

    const { BufferTarget, CanvasSource, Mp4OutputFormat, Output, QUALITY_MEDIUM } =
      await import('mediabunny');

    const seconds = Math.min(EXPORT_MAX_DURATION_TICKS / TICKS_PER_SECOND, spec.max_duration_ticks / TICKS_PER_SECOND);
    const fps = spec.fps_num / Math.max(1, spec.fps_den);
    const frames = Math.max(1, Math.round(seconds * fps));
    const target = new BufferTarget();
    const output = new Output({
      format: new Mp4OutputFormat(),
      target,
    });
    const source = new CanvasSource(canvas, { codec: 'avc', bitrate: QUALITY_MEDIUM });
    output.addVideoTrack(source, { frameRate: fps });
    await output.start();
    yield { percent: 2, stage: 'encoding', message: 'start' };

    const pool = new MediaPool();
    try {
      for (let index = 0; index < frames; index += 1) {
        if (signal.aborted) {
          await output.cancel();
          throw new DOMException('Aborted', 'AbortError');
        }
        const atTicks = Math.round((index / fps) * TICKS_PER_SECOND);
        await composeFrame(ctx, canvas.width, canvas.height, document, atTicks, assets, pool);
        await source.add(index / fps, 1 / fps);
        if (index % 15 === 0) {
          yield {
            percent: Math.min(98, Math.round((index / frames) * 96) + 2),
            stage: 'encoding',
            message: `${index}`,
          };
        }
      }
    } finally {
      pool.dispose();
    }
    source.close();
    await output.finalize();
    const buffer = target.buffer;
    if (!buffer) throw new Error('empty_export');
    yield {
      percent: 100,
      stage: 'encoding',
      message: 'done',
      blob: new Blob([buffer], { type: 'video/mp4' }),
    };
  }
}
