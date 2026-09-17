import { describe, expect, it } from 'vitest';

import {
  kWeightingFilters,
  measureLoudness,
  normalizationGain,
  normalizeAudioBuffer,
  PEAK_CEILING_DBFS,
  TARGET_LUFS,
} from './loudness';

const RATE = 48_000;

function sine(amplitude: number, seconds: number, frequency = 1_000): Float32Array {
  const samples = new Float32Array(Math.round(seconds * RATE));
  for (let index = 0; index < samples.length; index += 1) {
    samples[index] = amplitude * Math.sin((2 * Math.PI * frequency * index) / RATE);
  }
  return samples;
}

function fakeBuffer(channels: Float32Array[]): AudioBuffer {
  return {
    sampleRate: RATE,
    length: channels[0]?.length ?? 0,
    numberOfChannels: channels.length,
    getChannelData: (index: number) => channels[index]!,
  } as unknown as AudioBuffer;
}

describe('kWeightingFilters', () => {
  it('reproduces the published 48 kHz coefficients', () => {
    const [shelf, highPass] = kWeightingFilters(RATE);
    expect(shelf.b0).toBeCloseTo(1.53512485958697, 6);
    expect(shelf.a1).toBeCloseTo(-1.69065929318241, 6);
    expect(highPass.a1).toBeCloseTo(-1.99004745483398, 6);
    expect(highPass.a2).toBeCloseTo(0.99007225036621, 6);
  });
});

describe('measureLoudness', () => {
  it('reads a stereo 1 kHz sine at −20 dBFS as about −20 LUFS', () => {
    const stats = measureLoudness([sine(0.1, 3), sine(0.1, 3)], RATE);
    expect(stats.integratedLufs).toBeCloseTo(-20, 0);
    expect(stats.samplePeakDbfs).toBeCloseTo(-20, 1);
  });

  it('gates silence out entirely', () => {
    const silent = new Float32Array(RATE);
    expect(measureLoudness([silent, silent], RATE).integratedLufs).toBe(-Infinity);
  });

  it('ignores quiet passages below the relative gate', () => {
    const loud = sine(0.1, 3);
    const withPause = new Float32Array(loud.length * 2);
    withPause.set(loud);
    withPause.set(sine(0.0005, 3), loud.length);
    const stats = measureLoudness([withPause, withPause], RATE);
    expect(stats.integratedLufs).toBeCloseTo(-20, 0);
  });
});

describe('normalizationGain', () => {
  it('lifts a quiet mix to the target', () => {
    const gain = normalizationGain({ integratedLufs: -20, samplePeakDbfs: -20 });
    expect(20 * Math.log10(gain)).toBeCloseTo(TARGET_LUFS + 20, 5);
  });

  it('stops at the peak ceiling instead of clipping', () => {
    const gain = normalizationGain({ integratedLufs: -20, samplePeakDbfs: -3 });
    expect(20 * Math.log10(gain)).toBeCloseTo(PEAK_CEILING_DBFS + 3, 5);
  });

  it('turns a loud mix down', () => {
    expect(normalizationGain({ integratedLufs: -8, samplePeakDbfs: -0.5 })).toBeLessThan(1);
  });

  it('leaves silence alone', () => {
    expect(normalizationGain({ integratedLufs: -Infinity, samplePeakDbfs: -Infinity })).toBe(1);
  });
});

describe('normalizeAudioBuffer', () => {
  it('rescales every channel in place to the target loudness', () => {
    const buffer = fakeBuffer([sine(0.05, 3), sine(0.05, 3)]);
    const gain = normalizeAudioBuffer(buffer);
    expect(gain).toBeGreaterThan(1);
    const after = measureLoudness([buffer.getChannelData(0), buffer.getChannelData(1)], RATE);
    expect(after.integratedLufs).toBeCloseTo(TARGET_LUFS, 0);
    expect(after.samplePeakDbfs).toBeLessThanOrEqual(PEAK_CEILING_DBFS + 1e-6);
  });
});
