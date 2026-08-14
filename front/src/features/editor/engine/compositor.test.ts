import { describe, expect, it } from 'vitest';

import { emptyDocument } from './canonical';
import { resolveFrame } from './compositor';
import type { CanonicalDocument, TimelineElement } from './ports';
import { TICKS_PER_SECOND } from './ports';

function clipElement(overrides: Partial<TimelineElement> = {}): TimelineElement {
  return {
    id: 'el_clip',
    type: 'clip',
    track_id: 'trk_video',
    asset_id: 'ast_1',
    start_ticks: 0,
    duration_ticks: 2 * TICKS_PER_SECOND,
    source_in_ticks: 0,
    source_out_ticks: 2 * TICKS_PER_SECOND,
    volume_millipercent: 100_000,
    speed_millipercent: 100_000,
    text: null,
    caption_language: null,
    ...overrides,
  };
}

function documentWithClip(overrides: Partial<TimelineElement> = {}): CanonicalDocument {
  const document = emptyDocument(1080, 1920);
  document.tracks.find((track) => track.kind === 'video')!.elements.push(clipElement(overrides));
  return document;
}

describe('resolveFrame — clip resolution', () => {
  it('resolves no clip when nothing covers the requested tick', () => {
    const document = documentWithClip();
    const layers = resolveFrame(document, 3 * TICKS_PER_SECOND);
    expect(layers.clip).toBeNull();
  });

  it('resolves the clip and matching source time at 1x speed', () => {
    const document = documentWithClip();
    const layers = resolveFrame(document, TICKS_PER_SECOND);
    expect(layers.clip).not.toBeNull();
    expect(layers.clip!.asset_id).toBe('ast_1');
    expect(layers.clip!.sourceSeconds).toBeCloseTo(1, 5);
  });

  it('is inclusive at the start tick and exclusive at the end tick', () => {
    const document = documentWithClip();
    expect(resolveFrame(document, 0).clip).not.toBeNull();
    expect(resolveFrame(document, 2 * TICKS_PER_SECOND).clip).toBeNull();
  });

  it('scales source time by speed_millipercent', () => {
    const document = documentWithClip({ speed_millipercent: 200_000 });
    const layers = resolveFrame(document, TICKS_PER_SECOND);
    // 1s of output at 2x speed = 2s of source advanced.
    expect(layers.clip!.sourceSeconds).toBeCloseTo(2, 5);
  });

  it('offsets by source_in_ticks for a trimmed clip', () => {
    const document = documentWithClip({ source_in_ticks: 5 * TICKS_PER_SECOND });
    const layers = resolveFrame(document, TICKS_PER_SECOND);
    expect(layers.clip!.sourceSeconds).toBeCloseTo(6, 5);
  });

  it('clamps volume into 0..1 from millipercent', () => {
    const document = documentWithClip({ volume_millipercent: 250_000 });
    const layers = resolveFrame(document, 0);
    expect(layers.clip!.volume).toBe(1);
  });
});

describe('resolveFrame — captions', () => {
  it('includes captions active at the requested tick only', () => {
    const document = documentWithClip();
    document.tracks.find((track) => track.kind === 'caption')!.elements.push({
      id: 'el_cap',
      type: 'caption',
      track_id: 'trk_caption',
      asset_id: null,
      start_ticks: TICKS_PER_SECOND,
      duration_ticks: TICKS_PER_SECOND,
      source_in_ticks: 0,
      source_out_ticks: TICKS_PER_SECOND,
      volume_millipercent: 100_000,
      speed_millipercent: 100_000,
      text: 'hello',
      caption_language: 'zh-CN',
    });
    expect(resolveFrame(document, 0).captions).toEqual([]);
    expect(resolveFrame(document, TICKS_PER_SECOND).captions).toEqual(['hello']);
    expect(resolveFrame(document, 2 * TICKS_PER_SECOND).captions).toEqual([]);
  });
});

describe('resolveFrame — overlay and canvas', () => {
  it('passes through the document brand_overlay and canvas size unchanged', () => {
    const document = documentWithClip();
    document.brand_overlay = { asset_id: 'ast_brand', x_milli: 10, y_milli: 10, width_milli: 200 };
    const layers = resolveFrame(document, 0);
    expect(layers.overlay).toEqual(document.brand_overlay);
    expect(layers.canvasWidth).toBe(1080);
    expect(layers.canvasHeight).toBe(1920);
  });
});
