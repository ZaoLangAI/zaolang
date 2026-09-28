import { describe, expect, it } from 'vitest';

import { emptyDocument } from './canonical';
import { layerVolumeAt, resolveAudioLayers } from './compositor';
import { volumeCurve } from './export-runner';
import type { TimelineElement } from './ports';
import { TICKS_PER_SECOND } from './ports';

const S = TICKS_PER_SECOND;

function audioClip(overrides: Partial<TimelineElement> = {}): TimelineElement {
  return {
    id: 'el_voice',
    type: 'clip',
    track_id: 'trk_audio',
    asset_id: 'ast_voice',
    start_ticks: 0,
    duration_ticks: 4 * S,
    source_in_ticks: 0,
    source_out_ticks: 4 * S,
    volume_millipercent: 100_000,
    speed_millipercent: 100_000,
    text: null,
    caption_language: null,
    effects: [],
    mask: null,
    animations: { channels: {} },
    transition_in: null,
    transition_out: null,
    ...overrides,
  };
}

const ramp = {
  channels: {
    volume: {
      kind: 'number' as const,
      points: [
        { at_ticks: 0, value: 0, easing: 'linear' as const },
        { at_ticks: 2 * S, value: 200_000, easing: 'linear' as const },
      ],
    },
  },
};

describe('layerVolumeAt', () => {
  it('lets a clip play up to 200% instead of clamping at 100%', () => {
    expect(layerVolumeAt(audioClip({ volume_millipercent: 150_000 }), S)).toBeCloseTo(1.5, 5);
    expect(layerVolumeAt(audioClip({ animations: ramp }), 2 * S)).toBeCloseTo(2, 5);
  });

  it('still bounds the gain to the canonical 0–200% range', () => {
    expect(layerVolumeAt(audioClip({ volume_millipercent: 900_000 }), 0)).toBe(2);
  });
});

describe('resolveAudioLayers', () => {
  it('reports a boosted volume keyframe to both preview and export', () => {
    const document = emptyDocument(1080, 1920);
    document.tracks
      .find((track) => track.kind === 'audio')!
      .elements.push(audioClip({ animations: ramp }));
    expect(resolveAudioLayers(document, 1.5 * S)[0]?.volume).toBeCloseTo(1.5, 5);
  });
});

describe('volumeCurve', () => {
  it('follows a keyframe ramp across a segment instead of holding its first value', () => {
    const curve = volumeCurve(audioClip({ animations: ramp }), 0, 2 * S, 5);
    expect(Array.from(curve)).toEqual([0, 0.5, 1, 1.5, 2]);
  });
});
