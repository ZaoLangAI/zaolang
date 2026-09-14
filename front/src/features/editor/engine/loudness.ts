/**
 * Integrated loudness of a mixed export, after ITU-R BS.1770 (the measure
 * behind "LUFS"): K-weighting, 400 ms blocks every 100 ms, an absolute gate
 * at −70 LUFS and a relative gate 10 LU below the ungated mean. Pure — the
 * caller hands in channel samples — so the numbers are testable without an
 * AudioContext.
 *
 * Normalisation targets −14 LUFS (what the short-video platforms normalise
 * playback to) but never lifts the sample peak above −1 dBFS: a mix whose
 * peaks leave no headroom comes out quieter than the target rather than
 * clipped. It is an export-time mastering step on the finished mix; the
 * live preview plays the unnormalised mix.
 */

export const TARGET_LUFS = -14;
export const PEAK_CEILING_DBFS = -1;

const BLOCK_HOPS = 4; // 400 ms blocks …
const HOP_SECONDS = 0.1; // … every 100 ms (75% overlap)
const ABSOLUTE_GATE_LUFS = -70;
const RELATIVE_GATE_LU = -10;
const LOUDNESS_OFFSET = -0.691;

export interface Biquad {
  b0: number;
  b1: number;
  b2: number;
  a1: number;
  a2: number;
}

/** The two K-weighting stages (high shelf, then high pass) for `sampleRate`,
 * from BS.1770's analog prototypes so any rate works, not just 48 kHz. */
export function kWeightingFilters(sampleRate: number): [Biquad, Biquad] {
  const shelfK = Math.tan((Math.PI * 1681.974450955533) / sampleRate);
  const shelfQ = 0.7071752369554196;
  const vh = 10 ** (3.999843853973347 / 20);
  const vb = vh ** 0.4996667741545416;
  const shelfA0 = 1 + shelfK / shelfQ + shelfK * shelfK;
  const shelf: Biquad = {
    b0: (vh + (vb * shelfK) / shelfQ + shelfK * shelfK) / shelfA0,
    b1: (2 * (shelfK * shelfK - vh)) / shelfA0,
    b2: (vh - (vb * shelfK) / shelfQ + shelfK * shelfK) / shelfA0,
    a1: (2 * (shelfK * shelfK - 1)) / shelfA0,
    a2: (1 - shelfK / shelfQ + shelfK * shelfK) / shelfA0,
  };
  const passK = Math.tan((Math.PI * 38.13547087602444) / sampleRate);
  const passQ = 0.5003270373238773;
  const passA0 = 1 + passK / passQ + passK * passK;
  const highPass: Biquad = {
    b0: 1,
    b1: -2,
    b2: 1,
    a1: (2 * (passK * passK - 1)) / passA0,
    a2: (1 - passK / passQ + passK * passK) / passA0,
  };
  return [shelf, highPass];
}

export interface LoudnessStats {
  /** `-Infinity` for silence (every block gated out). */
  integratedLufs: number;
  samplePeakDbfs: number;
}

function toDb(power: number, offset = 0): number {
  return power > 0 ? offset + 10 * Math.log10(power) : -Infinity;
}

export function measureLoudness(channels: readonly Float32Array[], sampleRate: number): LoudnessStats {
  const length = channels[0]?.length ?? 0;
  const hop = Math.max(1, Math.round(sampleRate * HOP_SECONDS));
  const hopCount = Math.floor(length / hop);
  // Squared K-weighted energy per 100 ms hop, summed over channels (both
  // stereo channels weigh 1.0). Blocks are sums of 4 hops, so the full
  // filtered signal never has to be held in memory.
  const hopEnergy = new Float64Array(hopCount);
  let totalEnergy = 0;
  let peak = 0;
  const [shelf, highPass] = kWeightingFilters(sampleRate);
  for (const samples of channels) {
    let x1 = 0;
    let x2 = 0;
    let y1 = 0;
    let y2 = 0;
    let z1 = 0;
    let z2 = 0;
    for (let index = 0; index < length; index += 1) {
      const x = samples[index] ?? 0;
      const magnitude = Math.abs(x);
      if (magnitude > peak) peak = magnitude;
      const y = shelf.b0 * x + shelf.b1 * x1 + shelf.b2 * x2 - shelf.a1 * y1 - shelf.a2 * y2;
      x2 = x1;
      x1 = x;
      const z = highPass.b0 * y + highPass.b1 * y1 + highPass.b2 * y2 - highPass.a1 * z1 - highPass.a2 * z2;
      y2 = y1;
      y1 = y;
      z2 = z1;
      z1 = z;
      const energy = z * z;
      totalEnergy += energy;
      const slot = Math.floor(index / hop);
      if (slot < hopCount) hopEnergy[slot] = (hopEnergy[slot] ?? 0) + energy;
    }
  }
  const samplePeakDbfs = peak > 0 ? 20 * Math.log10(peak) : -Infinity;

  const blocks: number[] = [];
  for (let start = 0; start + BLOCK_HOPS <= hopCount; start += 1) {
    let energy = 0;
    for (let offset = 0; offset < BLOCK_HOPS; offset += 1) energy += hopEnergy[start + offset] ?? 0;
    blocks.push(energy / (BLOCK_HOPS * hop));
  }
  // Shorter than one block: measure the whole clip as a single block.
  if (blocks.length === 0 && length > 0) blocks.push(totalEnergy / length);

  const aboveAbsolute = blocks.filter((power) => toDb(power, LOUDNESS_OFFSET) > ABSOLUTE_GATE_LUFS);
  if (aboveAbsolute.length === 0) return { integratedLufs: -Infinity, samplePeakDbfs };
  const ungatedMean = aboveAbsolute.reduce((sum, power) => sum + power, 0) / aboveAbsolute.length;
  const relativeGate = toDb(ungatedMean, LOUDNESS_OFFSET) + RELATIVE_GATE_LU;
  const gated = aboveAbsolute.filter((power) => toDb(power, LOUDNESS_OFFSET) > relativeGate);
  const gatedMean = gated.reduce((sum, power) => sum + power, 0) / Math.max(1, gated.length);
  return { integratedLufs: toDb(gatedMean, LOUDNESS_OFFSET), samplePeakDbfs };
}

/** Linear gain that brings `stats` to `targetLufs` without pushing the
 * sample peak past `peakCeilingDbfs`. Silence is left alone. */
export function normalizationGain(
  stats: LoudnessStats,
  targetLufs = TARGET_LUFS,
  peakCeilingDbfs = PEAK_CEILING_DBFS,
): number {
  if (!Number.isFinite(stats.integratedLufs)) return 1;
  let gainDb = targetLufs - stats.integratedLufs;
  if (Number.isFinite(stats.samplePeakDbfs)) {
    gainDb = Math.min(gainDb, peakCeilingDbfs - stats.samplePeakDbfs);
  }
  return 10 ** (gainDb / 20);
}

/** Measures and rescales `buffer` in place; returns the applied gain. */
export function normalizeAudioBuffer(buffer: AudioBuffer): number {
  const channels = Array.from({ length: buffer.numberOfChannels }, (_, index) =>
    buffer.getChannelData(index),
  );
  const gain = normalizationGain(measureLoudness(channels, buffer.sampleRate));
  if (gain !== 1) {
    for (const samples of channels) {
      for (let index = 0; index < samples.length; index += 1) {
        samples[index] = (samples[index] ?? 0) * gain;
      }
    }
  }
  return gain;
}
