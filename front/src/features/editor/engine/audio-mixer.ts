/**
 * Live-preview audio, built on decoded AudioBuffers + AudioBufferSourceNode
 * scheduling rather than reseeking a playing <video>/<audio> element every
 * animation frame — that reseek-per-frame model is exactly what the visual
 * compositor still uses (`compositor.ts`'s `seekVideo`) and is why preview
 * audio was muted before this. Sample-accurate buffer playback sidesteps
 * that glitch entirely, and shares its decode/cache shape with the export
 * mixer (`export-runner.ts`) — both read the same `resolveAudioLayers`
 * truth, so preview and export never drift apart.
 */

import { resolveAudioLayers } from './compositor';
import type { CanonicalDocument } from './ports';

interface PlayingSource {
  node: AudioBufferSourceNode;
  gain: GainNode;
}

export class AudioMixer {
  private readonly context: AudioContext;
  private readonly buffers = new Map<string, Promise<AudioBuffer | null>>();
  private readonly playing = new Map<string, PlayingSource>();

  constructor() {
    this.context = new AudioContext();
  }

  private bufferFor(assetId: string, url: string): Promise<AudioBuffer | null> {
    let pending = this.buffers.get(assetId);
    if (!pending) {
      pending = fetch(url)
        .then((response) => response.arrayBuffer())
        .then((data) => this.context.decodeAudioData(data))
        .catch(() => null);
      this.buffers.set(assetId, pending);
    }
    return pending;
  }

  private stopOne(elementId: string): void {
    const source = this.playing.get(elementId);
    if (!source) return;
    try {
      source.node.stop();
    } catch {
      // Already stopped/ended — nothing to clean up twice.
    }
    source.node.disconnect();
    source.gain.disconnect();
    this.playing.delete(elementId);
  }

  /**
   * Reconciles playing sources with what should be active at `atTicks`.
   * Cheap to call every rAF tick: a node is only started or stopped when
   * the active layer set (diffed by element id) actually changes — a clip
   * that's still playing is left alone, so steady playback never restarts
   * or glitches. `assetUrls` is the same asset-id→signed-URL map the video
   * preview already resolves from `ResolvedAsset[]`.
   */
  sync(document: CanonicalDocument, atTicks: number, assetUrls: Map<string, string>): void {
    const layers = resolveAudioLayers(document, atTicks);
    const nextIds = new Set(layers.map((layer) => layer.element_id));
    for (const elementId of this.playing.keys()) {
      if (!nextIds.has(elementId)) this.stopOne(elementId);
    }
    for (const layer of layers) {
      if (this.playing.has(layer.element_id)) continue;
      const url = assetUrls.get(layer.asset_id);
      if (!url) continue;
      const elementId = layer.element_id;
      void this.bufferFor(layer.asset_id, url).then((buffer) => {
        // The layer may have stopped being active (or already started via
        // a later sync) by the time decoding finishes — never resurrect it.
        if (!buffer || this.playing.has(elementId)) return;
        const gain = this.context.createGain();
        gain.gain.value = layer.volume;
        gain.connect(this.context.destination);
        const node = this.context.createBufferSource();
        node.buffer = buffer;
        node.playbackRate.value = layer.speedFactor;
        node.connect(gain);
        node.start(0, Math.min(layer.sourceSeconds, Math.max(0, buffer.duration - 0.01)));
        node.onended = () => {
          if (this.playing.get(elementId)?.node === node) this.playing.delete(elementId);
        };
        this.playing.set(elementId, { node, gain });
      });
    }
  }

  /** Must be called from inside a user-gesture handler (e.g. the play button's onClick) — autoplay policy. */
  async resume(): Promise<void> {
    if (this.context.state === 'suspended') await this.context.resume();
  }

  stopAll(): void {
    for (const elementId of [...this.playing.keys()]) this.stopOne(elementId);
  }

  dispose(): void {
    this.stopAll();
    void this.context.close();
  }
}
