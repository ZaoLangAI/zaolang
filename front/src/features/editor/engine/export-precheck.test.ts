import { describe, expect, it } from 'vitest';

import { emptyDocument } from './canonical';
import { runStructuralPrecheck, sampleTicks } from './export-precheck';
import type { AnimatableProperty, CanonicalDocument, TimelineElement } from './ports';
import { TICKS_PER_SECOND } from './ports';

function clipElement(overrides: Partial<TimelineElement> = {}): TimelineElement {
  return {
    id: 'el_clip',
    type: 'clip',
    track_id: 'trk_video',
    asset_id: 'ast_1',
    start_ticks: 0,
    duration_ticks: 4 * TICKS_PER_SECOND,
    source_in_ticks: 0,
    source_out_ticks: 4 * TICKS_PER_SECOND,
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

function documentWithClip(overrides: Partial<TimelineElement> = {}): CanonicalDocument {
  const document = emptyDocument(1080, 1920);
  document.tracks.find((track) => track.kind === 'video')!.elements.push(clipElement(overrides));
  return document;
}

function withAnimation(property: AnimatableProperty, value: number): Partial<TimelineElement> {
  return {
    animations: { channels: { [property]: { kind: 'number', points: [{ at_ticks: 0, value }] } } },
  };
}

describe('sampleTicks', () => {
  it('spreads samples evenly from 0 to just under the duration', () => {
    expect(sampleTicks(10 * TICKS_PER_SECOND, 5)).toEqual([
      0,
      Math.round((10 * TICKS_PER_SECOND - 1) * 0.25),
      Math.round((10 * TICKS_PER_SECOND - 1) * 0.5),
      Math.round((10 * TICKS_PER_SECOND - 1) * 0.75),
      10 * TICKS_PER_SECOND - 1,
    ]);
  });

  it('returns a single sample at 0 when only one is requested', () => {
    expect(sampleTicks(10 * TICKS_PER_SECOND, 1)).toEqual([0]);
  });
});

describe('runStructuralPrecheck', () => {
  it('reports no issues for a clip that fully covers the sampled duration', () => {
    const document = documentWithClip();
    const result = runStructuralPrecheck(document, 4 * TICKS_PER_SECOND, 5);
    expect(result.issues).toEqual([]);
    expect(result.samples).toHaveLength(5);
  });

  it('flags a blank_frame where nothing is active at that tick', () => {
    // Clip only covers the first 2s of a 4s timeline — the later samples land past it.
    const document = documentWithClip({ duration_ticks: 2 * TICKS_PER_SECOND });
    const result = runStructuralPrecheck(document, 4 * TICKS_PER_SECOND, 5);
    const kinds = result.issues.map((issue) => issue.kind);
    expect(kinds).toContain('blank_frame');
  });

  it('does not flag blank_frame when a caption alone covers the tick', () => {
    const document = emptyDocument(1080, 1920);
    const captionTrack = document.tracks.find((track) => track.kind === 'caption')!;
    captionTrack.elements.push(
      clipElement({
        id: 'el_caption',
        type: 'caption',
        track_id: captionTrack.id,
        asset_id: null,
        text: 'hello',
      }),
    );
    const result = runStructuralPrecheck(document, 4 * TICKS_PER_SECOND, 1);
    expect(result.issues).toEqual([]);
  });

  it('flags clip_off_canvas when a pan keyframe drifts the clip fully out of frame', () => {
    // Canvas is 1080 wide; shifting by +2000 milli (200% of width) moves the
    // entire cover-fit layer well past the right edge.
    const document = documentWithClip(withAnimation('transform.x_milli', 2_000));
    const result = runStructuralPrecheck(document, 4 * TICKS_PER_SECOND, 1);
    expect(result.issues).toEqual([{ kind: 'clip_off_canvas', atTicks: 0 }]);
  });

  it('flags clip_off_canvas for a zero scale', () => {
    const document = documentWithClip(withAnimation('transform.scale_millipercent', 0));
    const result = runStructuralPrecheck(document, 4 * TICKS_PER_SECOND, 1);
    expect(result.issues).toEqual([{ kind: 'clip_off_canvas', atTicks: 0 }]);
  });

  it('does not flag a clip that is merely panned but still overlapping the canvas', () => {
    const document = documentWithClip(withAnimation('transform.x_milli', 100));
    const result = runStructuralPrecheck(document, 4 * TICKS_PER_SECOND, 1);
    expect(result.issues).toEqual([]);
  });
});
