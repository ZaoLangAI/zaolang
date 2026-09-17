import { TICKS_PER_SECOND } from './ports';

/**
 * Peak amplitude (0..1) per bucket across `[startSec, endSec)` of `buffer`,
 * downmixed across all channels. Buckets — not a raw per-sample readout —
 * because a clip a few seconds long already holds tens of thousands of
 * samples per channel; the timeline only ever needs one bar's worth of
 * detail per few timeline pixels.
 */
export function computePeaks(
  buffer: AudioBuffer,
  bucketCount: number,
  startSec: number,
  endSec: number,
): number[] {
  const sampleRate = buffer.sampleRate;
  const startSample = Math.max(0, Math.floor(startSec * sampleRate));
  const endSample = Math.min(buffer.length, Math.ceil(endSec * sampleRate));
  const totalSamples = Math.max(1, endSample - startSample);
  const samplesPerBucket = Math.max(1, Math.floor(totalSamples / bucketCount));
  const channels = Array.from({ length: buffer.numberOfChannels }, (_, i) =>
    buffer.getChannelData(i),
  );

  const peaks: number[] = [];
  for (let bucket = 0; bucket < bucketCount; bucket++) {
    const bucketStart = startSample + bucket * samplesPerBucket;
    const bucketEnd = Math.min(endSample, bucketStart + samplesPerBucket);
    let peak = 0;
    for (let i = bucketStart; i < bucketEnd; i++) {
      for (const channel of channels) {
        const value = Math.abs(channel[i] ?? 0);
        if (value > peak) peak = value;
      }
    }
    peaks.push(Math.min(1, peak));
  }
  return peaks;
}

export function ticksToSeconds(ticks: number): number {
  return ticks / TICKS_PER_SECOND;
}
