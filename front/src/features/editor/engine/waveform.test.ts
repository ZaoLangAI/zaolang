import { describe, expect, it } from 'vitest';

import { TICKS_PER_SECOND } from './ports';
import { computePeaks, ticksToSeconds } from './waveform';

/** Minimal `AudioBuffer` stand-in — jsdom has no real decoder, and
 * `computePeaks` only ever reads `sampleRate`/`length`/`numberOfChannels`/
 * `getChannelData`. */
function fakeBuffer(channelsData: number[][], sampleRate = 10): AudioBuffer {
  return {
    sampleRate,
    length: channelsData[0]?.length ?? 0,
    numberOfChannels: channelsData.length,
    getChannelData: (index: number) => Float32Array.from(channelsData[index]!),
  } as unknown as AudioBuffer;
}

describe('computePeaks', () => {
  it('returns one peak per bucket across the requested range', () => {
    const buffer = fakeBuffer([[0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]]);
    const peaks = computePeaks(buffer, 5, 0, 1);
    expect(peaks).toHaveLength(5);
  });

  it('picks the max absolute amplitude within each bucket', () => {
    const buffer = fakeBuffer([[0.1, -0.9, 0.2, 0.05]]);
    const peaks = computePeaks(buffer, 2, 0, 0.4);
    expect(peaks[0]).toBeCloseTo(0.9, 5);
    expect(peaks[1]).toBeCloseTo(0.2, 5);
  });

  it('downmixes across channels by taking the loudest one per sample', () => {
    const buffer = fakeBuffer([
      [0.1, 0.1],
      [0.8, -0.05],
    ]);
    const peaks = computePeaks(buffer, 2, 0, 0.2);
    expect(peaks[0]).toBeCloseTo(0.8, 5);
    expect(peaks[1]).toBeCloseTo(0.1, 5);
  });

  it('restricts sampling to the given [startSec, endSec) window', () => {
    // Loud spike sits entirely before `startSec` — must not leak into any bucket.
    const buffer = fakeBuffer([[0.99, 0.99, 0.1, 0.1, 0.1, 0.1]]);
    const peaks = computePeaks(buffer, 2, 0.2, 0.6);
    expect(Math.max(...peaks)).toBeCloseTo(0.1, 5);
  });

  it('clamps peaks to at most 1', () => {
    const buffer = fakeBuffer([[1.5]]);
    const peaks = computePeaks(buffer, 1, 0, 0.1);
    expect(peaks[0]).toBe(1);
  });
});

describe('ticksToSeconds', () => {
  it('converts editor ticks to seconds', () => {
    expect(ticksToSeconds(TICKS_PER_SECOND)).toBe(1);
    expect(ticksToSeconds(TICKS_PER_SECOND * 2.5)).toBe(2.5);
  });
});
