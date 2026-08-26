import { composeFrame, MediaPool, resolveAudioLayers } from './compositor';
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

const AUDIO_SAMPLE_RATE = 48_000;
const AUDIO_CHANNELS = 2;

function documentHasAudibleContent(document: CanonicalDocument): boolean {
  return document.tracks.some(
    (track) =>
      (track.kind === 'audio' || track.kind === 'video') &&
      !track.muted &&
      track.elements.some((element) => element.asset_id),
  );
}

/**
 * Every tick where an audio-track or video-track element starts or ends —
 * `resolveAudioLayers`'s output only changes at these points, so sampling
 * once per segment (instead of once per exported video frame) gets an exact
 * mix without per-frame scheduling overhead or boundary clicks.
 */
function audioBreakpoints(document: CanonicalDocument, maxTicks: number): number[] {
  const points = new Set<number>([0, maxTicks]);
  for (const track of document.tracks) {
    if (track.kind !== 'video' && track.kind !== 'audio') continue;
    for (const element of track.elements) {
      const start = element.start_ticks;
      const end = start + element.duration_ticks;
      if (start > 0 && start < maxTicks) points.add(start);
      if (end > 0 && end < maxTicks) points.add(end);
    }
  }
  return [...points].sort((a, b) => a - b);
}

/**
 * Renders the full mixed audio track for the export's duration via an
 * `OfflineAudioContext`, reading the same `resolveAudioLayers` truth the
 * live preview mixer does. Returns null when nothing is actually audible,
 * so the caller can skip adding an audio track entirely.
 */
async function renderMixedAudio(
  document: CanonicalDocument,
  seconds: number,
  assets: ResolvedAsset[],
): Promise<AudioBuffer | null> {
  if (seconds <= 0) return null;
  const offline = new OfflineAudioContext(
    AUDIO_CHANNELS,
    Math.ceil(seconds * AUDIO_SAMPLE_RATE),
    AUDIO_SAMPLE_RATE,
  );
  const assetUrls = new Map(assets.map((asset) => [asset.asset_id, asset.url]));
  const bufferCache = new Map<string, Promise<AudioBuffer | null>>();
  const bufferFor = (assetId: string): Promise<AudioBuffer | null> => {
    let pending = bufferCache.get(assetId);
    if (!pending) {
      const url = assetUrls.get(assetId);
      pending = url
        ? fetch(url)
            .then((response) => response.arrayBuffer())
            .then((data) => offline.decodeAudioData(data))
            .catch(() => null)
        : Promise.resolve(null);
      bufferCache.set(assetId, pending);
    }
    return pending;
  };

  const maxTicks = Math.round(seconds * TICKS_PER_SECOND);
  const breakpoints = audioBreakpoints(document, maxTicks);
  let scheduled = false;
  for (let index = 0; index < breakpoints.length - 1; index += 1) {
    const start = breakpoints[index] ?? 0;
    const end = breakpoints[index + 1] ?? start;
    for (const layer of resolveAudioLayers(document, start)) {
      const buffer = await bufferFor(layer.asset_id);
      if (!buffer) continue;
      const available = Math.max(0, buffer.duration - layer.sourceSeconds);
      const durationSeconds = Math.min(
        ((end - start) / TICKS_PER_SECOND) * layer.speedFactor,
        available,
      );
      if (durationSeconds <= 0) continue;
      const gain = offline.createGain();
      gain.gain.value = layer.volume;
      gain.connect(offline.destination);
      const node = offline.createBufferSource();
      node.buffer = buffer;
      node.playbackRate.value = layer.speedFactor;
      node.connect(gain);
      node.start(start / TICKS_PER_SECOND, layer.sourceSeconds, durationSeconds);
      scheduled = true;
    }
  }
  return scheduled ? offline.startRendering() : null;
}

/**
 * Sequential browser export. Renders the same edited timeline the preview
 * shows (via `compositor.ts`) frame by frame into a canvas, then encodes it
 * with mediabunny. Classic BufferTarget holds the file in memory, so product
 * hard limits (30s / 1080p / 80MB estimate) are the stop-gate until a
 * streaming encoder lands. Audio is mixed offline from every audible layer
 * (`renderMixedAudio`) and added as a second track alongside the picture.
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

    const {
      AudioBufferSource,
      BufferTarget,
      CanvasSource,
      Mp4OutputFormat,
      Output,
      QUALITY_MEDIUM,
    } = await import('mediabunny');

    const seconds = Math.min(
      EXPORT_MAX_DURATION_TICKS / TICKS_PER_SECOND,
      spec.max_duration_ticks / TICKS_PER_SECOND,
    );
    const fps = spec.fps_num / Math.max(1, spec.fps_den);
    const frames = Math.max(1, Math.round(seconds * fps));
    const target = new BufferTarget();
    const output = new Output({
      format: new Mp4OutputFormat(),
      target,
    });
    const source = new CanvasSource(canvas, { codec: 'avc', bitrate: QUALITY_MEDIUM });
    output.addVideoTrack(source, { frameRate: fps });
    // `addAudioTrack` can only be called before `output.start()`, but the
    // mixed buffer itself isn't rendered until after the picture loop below
    // — so register the track now from a cheap synchronous document check,
    // fill it in later, and `.close()` it either way.
    const audioSource = documentHasAudibleContent(document)
      ? new AudioBufferSource({ codec: 'aac', bitrate: QUALITY_MEDIUM })
      : null;
    if (audioSource) output.addAudioTrack(audioSource);
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

    if (audioSource) {
      yield { percent: 98, stage: 'encoding', message: 'audio' };
      const mixed = await renderMixedAudio(document, seconds, assets);
      if (mixed) await audioSource.add(mixed);
      audioSource.close();
    }

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
