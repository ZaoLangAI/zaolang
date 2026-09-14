import type { MetadataTags } from 'mediabunny';

import { composeFrame, MediaPool, resolveAudioLayers } from './compositor';
import {
  TICKS_PER_SECOND,
  type CanonicalDocument,
  type CapabilityReport,
  type ExportProgress,
  type ExportRenderOptions,
  type RendererBackend,
  type ResolvedAsset,
  type VariantSpec,
} from './ports';

const AUDIO_SAMPLE_RATE = 48_000;
const AUDIO_CHANNELS = 2;

function evenPixel(value: number): number {
  return Math.max(2, Math.floor(value / 2) * 2);
}

/** Round a delivery spec to even pixels for H.264, without downscaling. */
export function fitExportCanvas(width: number, height: number): { width: number; height: number } {
  return { width: evenPixel(width), height: evenPixel(height) };
}

export const AIGC_CONTENT_PRODUCER = 'zaolang';

/**
 * The implicit "AI-generated" label written into every exported MP4
 * (《人工智能生成合成内容标识办法》): the standard `AIGC` JSON in the comment
 * tag, plus a human-readable description. Pure, so the exact tags are
 * testable without encoding a file. The visible label is the separate,
 * optional `ExportRenderOptions.aiLabel`.
 */
export function aigcMetadataTags(exportedAt: Date): MetadataTags {
  const aigc = {
    Label: '1',
    ContentProducer: AIGC_CONTENT_PRODUCER,
    ProduceID: '',
    ReservedCode1: '',
    ContentPropagator: '',
    PropagateID: '',
    ReservedCode2: '',
  };
  return {
    comment: `AIGC ${JSON.stringify(aigc)}`,
    description: 'AI-generated content (AI 生成内容)',
    date: exportedAt,
  };
}

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
      // A `volume` keyframe channel means `resolveAudioLayers`' resolved
      // volume can also change *within* a clip, not just at its start/end —
      // add each keyframe tick so the offline mix re-samples there too,
      // instead of holding one gain value for the whole clip.
      for (const point of element.animations.channels.volume?.points ?? []) {
        if (point.at_ticks > 0 && point.at_ticks < maxTicks) points.add(point.at_ticks);
      }
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
 * with mediabunny at the delivery variant's own resolution. Classic
 * BufferTarget still holds the file in memory — a long or high-resolution
 * cut can OOM the tab; that is accepted until a streaming encoder lands.
 * Audio is mixed offline from every audible layer (`renderMixedAudio`) and
 * added as a second track alongside the picture.
 */
export class SequentialExportRunner implements RendererBackend {
  async preflight(spec: VariantSpec): Promise<CapabilityReport> {
    const reasons: string[] = [];
    const pixels = spec.width * spec.height;
    const chrome = /Chrome|Edg\//.test(navigator.userAgent) && !/Mobile/.test(navigator.userAgent);
    if (!chrome) reasons.push('browser');
    const estimated = Math.ceil((spec.max_duration_ticks / TICKS_PER_SECOND) * pixels * 0.12);
    if (typeof VideoEncoder === 'undefined') reasons.push('webcodecs');
    return { ok: reasons.length === 0, reasons, estimated_bytes: estimated };
  }

  async *export(
    spec: VariantSpec,
    document: CanonicalDocument,
    assets: ResolvedAsset[],
    signal: AbortSignal,
    options: ExportRenderOptions = {},
  ): AsyncIterable<ExportProgress> {
    const report = await this.preflight(spec);
    if (!report.ok) {
      throw new Error(`export_preflight:${report.reasons.join(',')}`);
    }

    const canvas = window.document.createElement('canvas');
    const fitted = fitExportCanvas(spec.width, spec.height);
    canvas.width = fitted.width;
    canvas.height = fitted.height;
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

    const seconds = spec.max_duration_ticks / TICKS_PER_SECOND;
    const fps = spec.fps_num / Math.max(1, spec.fps_den);
    const frames = Math.max(1, Math.round(seconds * fps));
    const target = new BufferTarget();
    const output = new Output({
      format: new Mp4OutputFormat(),
      target,
    });
    // The implicit AI label, written into the file itself on every export;
    // tags can only be set before `start()`.
    output.setMetadataTags(aigcMetadataTags(new Date()));
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
        await composeFrame(ctx, canvas.width, canvas.height, document, atTicks, assets, pool, {
          aiLabel: options.aiLabel,
        });
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
