import { describe, expect, it } from 'vitest';

import { emptyDocument } from './canonical';
import { activeVideoLayer, resolveAudioLayers, resolveFrame } from './compositor';
import type { CanonicalDocument, TimelineElement, TimelineTrack } from './ports';
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

  it('clamps volume into 0..2 (the canonical 0–200%) from millipercent', () => {
    const document = documentWithClip({ volume_millipercent: 250_000 });
    const layers = resolveFrame(document, 0);
    expect(layers.clip!.volume).toBe(2);
  });

  it('resolves volume from a keyframed channel instead of the static value when present', () => {
    const document = documentWithClip({
      volume_millipercent: 100_000,
      animations: {
        channels: {
          volume: {
            kind: 'number',
            points: [
              { at_ticks: 0, value: 0 },
              { at_ticks: TICKS_PER_SECOND, value: 100_000 },
            ],
          },
        },
      },
    });
    expect(resolveFrame(document, 0).clip!.volume).toBeCloseTo(0, 5);
    expect(resolveFrame(document, TICKS_PER_SECOND / 2).clip!.volume).toBeCloseTo(0.5, 5);
  });

  it('falls back to the static volume_millipercent when there is no volume channel', () => {
    const document = documentWithClip({ volume_millipercent: 40_000 });
    expect(resolveFrame(document, TICKS_PER_SECOND).clip!.volume).toBeCloseTo(0.4, 5);
  });
});

describe('resolveFrame — effects and mask', () => {
  it('carries the element effects and mask through to the resolved clip layer', () => {
    const mask = {
      shape: 'rect' as const,
      x_milli: 0,
      y_milli: 0,
      width_milli: 1000,
      height_milli: 1000,
      feather_millipercent: 5_000,
    };
    const document = documentWithClip({
      effects: [{ type: 'blur', params: { intensity: 30 } }],
      mask,
    });
    const layers = resolveFrame(document, 0);
    expect(layers.clip!.effects).toEqual([{ type: 'blur', params: { intensity: 30 } }]);
    expect(layers.clip!.mask).toEqual(mask);
  });

  it('defaults to no effects and no mask', () => {
    const layers = resolveFrame(documentWithClip(), 0);
    expect(layers.clip!.effects).toEqual([]);
    expect(layers.clip!.mask).toBeNull();
  });
});

describe('resolveFrame — transitions', () => {
  function overlappingClips(overrides: {
    outgoing?: Partial<TimelineElement>;
    incoming?: Partial<TimelineElement>;
  }): CanonicalDocument {
    const document = emptyDocument(1080, 1920);
    const track = document.tracks.find((t) => t.kind === 'video')!;
    // outgoing: 0..2s, incoming: 1..3s — a 1s overlap.
    track.elements.push(
      clipElement({
        id: 'el_out',
        asset_id: 'ast_out',
        start_ticks: 0,
        duration_ticks: 2 * TICKS_PER_SECOND,
        ...overrides.outgoing,
      }),
      clipElement({
        id: 'el_in',
        asset_id: 'ast_in',
        start_ticks: TICKS_PER_SECOND,
        duration_ticks: 2 * TICKS_PER_SECOND,
        ...overrides.incoming,
      }),
    );
    return document;
  }

  it('falls back to the newer clip when no transition is configured on either overlapping element', () => {
    const document = overlappingClips({});
    const layers = resolveFrame(document, TICKS_PER_SECOND + 100);
    expect(layers.clip!.asset_id).toBe('ast_in');
    expect(layers.transitionLayer).toBeNull();
  });

  it('crossfades both clips with complementary weights across the overlap window', () => {
    const document = overlappingClips({
      outgoing: { transition_out: { type: 'crossfade', duration_ticks: TICKS_PER_SECOND } },
    });
    // Overlap window is [1s, 2s). At the very start, outgoing should dominate.
    const start = resolveFrame(document, TICKS_PER_SECOND);
    expect(start.clip!.asset_id).toBe('ast_out');
    expect(start.clip!.opacity).toBeCloseTo(1, 2);
    expect(start.transitionLayer!.asset_id).toBe('ast_in');
    expect(start.transitionLayer!.opacity).toBeCloseTo(0, 2);

    const middle = resolveFrame(document, TICKS_PER_SECOND + TICKS_PER_SECOND / 2);
    expect(middle.clip!.opacity).toBeCloseTo(0.5, 2);
    expect(middle.transitionLayer!.opacity).toBeCloseTo(0.5, 2);

    const end = resolveFrame(document, 2 * TICKS_PER_SECOND - 1);
    expect(end.clip!.opacity).toBeCloseTo(0, 1);
    expect(end.transitionLayer!.opacity).toBeCloseTo(1, 1);
  });

  it('dip_to_black never shows two layers at once', () => {
    const document = overlappingClips({
      outgoing: { transition_out: { type: 'dip_to_black', duration_ticks: TICKS_PER_SECOND } },
    });
    const firstHalf = resolveFrame(document, TICKS_PER_SECOND + 100);
    expect(firstHalf.clip!.asset_id).toBe('ast_out');
    expect(firstHalf.transitionLayer).toBeNull();

    const secondHalf = resolveFrame(document, TICKS_PER_SECOND + TICKS_PER_SECOND / 2 + 100);
    expect(secondHalf.clip!.asset_id).toBe('ast_in');
    expect(secondHalf.transitionLayer).toBeNull();
  });

  it('prefers the outgoing clip transition_out over the incoming clip transition_in', () => {
    const document = overlappingClips({
      outgoing: { transition_out: { type: 'dip_to_black', duration_ticks: TICKS_PER_SECOND } },
      incoming: { transition_in: { type: 'crossfade', duration_ticks: TICKS_PER_SECOND } },
    });
    // dip_to_black (outgoing's own) should win, so no transitionLayer ever appears.
    expect(resolveFrame(document, TICKS_PER_SECOND + TICKS_PER_SECOND / 2).transitionLayer).toBeNull();
  });

  it('has no effect outside the overlap window', () => {
    const document = overlappingClips({
      outgoing: { transition_out: { type: 'crossfade', duration_ticks: TICKS_PER_SECOND } },
    });
    const beforeOverlap = resolveFrame(document, 500);
    expect(beforeOverlap.clip!.asset_id).toBe('ast_out');
    expect(beforeOverlap.clip!.opacity).toBe(1);
    expect(beforeOverlap.transitionLayer).toBeNull();
  });
});

describe('resolveFrame — opacity and transform keyframes', () => {
  it('defaults to full opacity and the identity transform with no channels', () => {
    const layers = resolveFrame(documentWithClip(), 0);
    expect(layers.clip!.opacity).toBe(1);
    expect(layers.clip!.transform).toEqual({
      xMilli: 0,
      yMilli: 0,
      scaleMillipercent: 100_000,
      rotationMillidegrees: 0,
    });
  });

  it('resolves an interpolated opacity fade between two keyframes', () => {
    const document = documentWithClip({
      animations: {
        channels: {
          opacity: {
            kind: 'number',
            points: [
              { at_ticks: 0, value: 0 },
              { at_ticks: TICKS_PER_SECOND, value: 100_000 },
            ],
          },
        },
      },
    });
    expect(resolveFrame(document, 0).clip!.opacity).toBeCloseTo(0, 5);
    expect(resolveFrame(document, TICKS_PER_SECOND / 2).clip!.opacity).toBeCloseTo(0.5, 5);
    expect(resolveFrame(document, TICKS_PER_SECOND).clip!.opacity).toBeCloseTo(1, 5);
  });

  it('resolves a pan/zoom transform independently from opacity', () => {
    const document = documentWithClip({
      animations: {
        channels: {
          'transform.x_milli': { kind: 'number', points: [{ at_ticks: 0, value: 300 }] },
          'transform.scale_millipercent': { kind: 'number', points: [{ at_ticks: 0, value: 150_000 }] },
        },
      },
    });
    const clip = resolveFrame(document, 0).clip!;
    expect(clip.transform.xMilli).toBe(300);
    expect(clip.transform.scaleMillipercent).toBe(150_000);
    expect(clip.transform.yMilli).toBe(0);
    expect(clip.opacity).toBe(1);
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
      effects: [],
      mask: null,
      animations: { channels: {} },
      transition_in: null,
      transition_out: null,
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

function extraTrack(kind: TimelineTrack['kind'], overrides: Partial<TimelineTrack> = {}): TimelineTrack {
  return { id: `trk_${kind}_extra`, kind, elements: [], order: 0, label: null, muted: false, ...overrides };
}

describe('activeVideoLayer — multi-track selection', () => {
  it('picks the higher-order track when both have content at the same tick', () => {
    const document = documentWithClip(); // trk_video, order 0
    const top = extraTrack('video', { order: 1 });
    top.elements.push(clipElement({ id: 'el_top', asset_id: 'ast_top', track_id: top.id }));
    document.tracks.push(top);

    const layer = activeVideoLayer(document, TICKS_PER_SECOND);
    expect(layer?.element.id).toBe('el_top');
  });

  it('falls through to a lower track when the top track has no content there', () => {
    const document = documentWithClip(); // covers 0..2s
    const top = extraTrack('video', {
      order: 1,
      elements: [clipElement({ id: 'el_top', asset_id: 'ast_top', start_ticks: 5 * TICKS_PER_SECOND })],
    });
    document.tracks.push(top);

    const layer = activeVideoLayer(document, TICKS_PER_SECOND);
    expect(layer?.element.id).toBe('el_clip');
  });

  it('skips a muted video track entirely, even if it would otherwise win', () => {
    const document = documentWithClip();
    const top = extraTrack('video', { order: 1, muted: true });
    top.elements.push(clipElement({ id: 'el_top', asset_id: 'ast_top', track_id: top.id }));
    document.tracks.push(top);

    const layer = activeVideoLayer(document, TICKS_PER_SECOND);
    expect(layer?.element.id).toBe('el_clip');
  });
});

describe('resolveAudioLayers', () => {
  it('mixes every non-muted audio track plus the visible video clip', () => {
    const document = documentWithClip(); // visible video clip, asset ast_1
    document.tracks.find((track) => track.kind === 'audio')!.elements.push(
      clipElement({ id: 'el_audio', asset_id: 'ast_audio', track_id: 'trk_audio' }),
    );
    const layers = resolveAudioLayers(document, TICKS_PER_SECOND);
    const assetIds = layers.map((layer) => layer.asset_id).sort();
    expect(assetIds).toEqual(['ast_1', 'ast_audio']);
  });

  it('excludes a muted audio track', () => {
    const document = documentWithClip();
    document.tracks.find((track) => track.kind === 'audio')!.muted = true;
    document.tracks.find((track) => track.kind === 'audio')!.elements.push(
      clipElement({ id: 'el_audio', asset_id: 'ast_audio', track_id: 'trk_audio' }),
    );
    const layers = resolveAudioLayers(document, TICKS_PER_SECOND);
    expect(layers.map((layer) => layer.asset_id)).toEqual(['ast_1']);
  });

  it('mixes multiple simultaneous audio tracks (BGM + dialogue)', () => {
    const document = emptyDocument(1080, 1920);
    const bgm = extraTrack('audio', {
      elements: [clipElement({ id: 'el_bgm', asset_id: 'ast_bgm', track_id: 'trk_bgm' })],
    });
    document.tracks.push(bgm);
    document.tracks.find((track) => track.kind === 'audio')!.elements.push(
      clipElement({ id: 'el_dialogue', asset_id: 'ast_dialogue', track_id: 'trk_audio' }),
    );
    const layers = resolveAudioLayers(document, TICKS_PER_SECOND);
    expect(layers.map((layer) => layer.asset_id).sort()).toEqual(['ast_bgm', 'ast_dialogue']);
  });

  it('excludes a hidden (occluded) video track — no sound from what is not shown', () => {
    const document = documentWithClip(); // trk_video, order 0, asset ast_1
    const top = extraTrack('video', { order: 1 });
    top.elements.push(clipElement({ id: 'el_top', asset_id: 'ast_top', track_id: top.id }));
    document.tracks.push(top);

    const layers = resolveAudioLayers(document, TICKS_PER_SECOND);
    expect(layers.map((layer) => layer.asset_id)).toEqual(['ast_top']);
  });

  it('resolves an audio clip volume from a keyframed channel over the playhead', () => {
    const document = emptyDocument(1080, 1920);
    document.tracks.find((track) => track.kind === 'audio')!.elements.push(
      clipElement({
        id: 'el_audio',
        asset_id: 'ast_audio',
        track_id: 'trk_audio',
        volume_millipercent: 100_000,
        animations: {
          channels: {
            volume: {
              kind: 'number',
              points: [
                { at_ticks: 0, value: 0 },
                { at_ticks: 2 * TICKS_PER_SECOND, value: 100_000 },
              ],
            },
          },
        },
      }),
    );
    const layers = resolveAudioLayers(document, TICKS_PER_SECOND);
    const audioLayer = layers.find((layer) => layer.asset_id === 'ast_audio')!;
    expect(audioLayer.volume).toBeCloseTo(0.5, 5);
  });

  it('derives a playbackRate-equivalent speedFactor from speed_millipercent', () => {
    const document = documentWithClip({ speed_millipercent: 150_000 });
    const layers = resolveAudioLayers(document, TICKS_PER_SECOND);
    expect(layers[0]!.speedFactor).toBeCloseTo(1.5, 5);
  });
});
