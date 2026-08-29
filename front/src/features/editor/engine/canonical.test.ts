import { describe, expect, it } from 'vitest';

import {
  applyBatch,
  BatchRolledBackError,
  cloneDocument,
  durationTicks,
  emptyDocument,
  validateBatch,
} from './canonical';
import type { CanonicalDocument, EditCommand } from './ports';
import { TICKS_PER_SECOND } from './ports';

function withClip(document: CanonicalDocument, overrides: Partial<CanonicalDocument['tracks'][number]['elements'][number]> = {}) {
  const track = document.tracks.find((item) => item.kind === 'video');
  if (!track) throw new Error('no video track');
  track.elements.push({
    id: 'el_clip',
    type: 'clip',
    track_id: track.id,
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
  });
  return document;
}

function apply(document: CanonicalDocument, commands: EditCommand[], knownAssets = new Set(['ast_1'])) {
  return applyBatch(document, commands, knownAssets);
}

describe('emptyDocument / durationTicks', () => {
  it('creates the four fixed tracks', () => {
    const document = emptyDocument();
    expect(document.tracks.map((track) => track.kind)).toEqual([
      'video',
      'audio',
      'caption',
      'overlay',
    ]);
    expect(document.tracks.every((track) => track.elements.length === 0)).toBe(true);
  });

  it('computes duration as the furthest element end', () => {
    const document = withClip(emptyDocument(), { start_ticks: TICKS_PER_SECOND, duration_ticks: TICKS_PER_SECOND });
    expect(durationTicks(document)).toBe(2 * TICKS_PER_SECOND);
  });
});

describe('validateBatch', () => {
  const base = { schema_version: 1 as const, batch_id: 'b1', expected_revision_id: null };

  it('accepts a well-formed batch', () => {
    const batch = validateBatch({ ...base, commands: [{ type: 'delete_elements', element_ids: ['el_1'] }] });
    expect(batch.commands).toHaveLength(1);
  });

  it('rejects a non-object input', () => {
    expect(() => validateBatch(null)).toThrow();
  });

  it('rejects an unsupported schema_version', () => {
    expect(() => validateBatch({ ...base, schema_version: 2, commands: [] })).toThrow();
  });

  it('rejects a missing batch_id', () => {
    expect(() =>
      validateBatch({ schema_version: 1, batch_id: '', expected_revision_id: null, commands: [] }),
    ).toThrow();
  });

  it('rejects empty commands', () => {
    expect(() => validateBatch({ ...base, commands: [] })).toThrow();
  });

  it('rejects batches over the per-batch command cap', () => {
    const commands = Array.from({ length: 101 }, () => ({ type: 'delete_elements', element_ids: [] }));
    expect(() => validateBatch({ ...base, commands })).toThrow();
  });

  it('rejects an unknown command type', () => {
    expect(() => validateBatch({ ...base, commands: [{ type: 'nuke_everything' }] })).toThrow();
  });

  it('rejects a generic path/value update', () => {
    expect(() =>
      validateBatch({ ...base, commands: [{ type: 'delete_elements', path: 'x', value: 1 }] }),
    ).toThrow('禁止通用路径更新');
  });
});

describe('applyBatch — insert_clip', () => {
  it('inserts a clip with the given fields and default volume/speed', () => {
    const result = apply(emptyDocument(), [
      { type: 'insert_clip', track_id: 'trk_video', asset_id: 'ast_1', at_ticks: 0, duration_ticks: TICKS_PER_SECOND },
    ]);
    const clip = result.tracks[0]!.elements[0]!;
    expect(clip.asset_id).toBe('ast_1');
    expect(clip.start_ticks).toBe(0);
    expect(clip.duration_ticks).toBe(TICKS_PER_SECOND);
    expect(clip.source_in_ticks).toBe(0);
    expect(clip.source_out_ticks).toBe(TICKS_PER_SECOND);
    expect(clip.volume_millipercent).toBe(100_000);
    expect(clip.speed_millipercent).toBe(100_000);
  });

  it('rolls back the whole batch when the asset is unknown', () => {
    const document = emptyDocument();
    expect(() =>
      apply(
        document,
        [{ type: 'insert_clip', track_id: 'trk_video', asset_id: 'ast_missing', at_ticks: 0, duration_ticks: 1 }],
        new Set(['ast_1']),
      ),
    ).toThrow(BatchRolledBackError);
    // The original document object passed in must be untouched.
    expect(document.tracks[0]!.elements).toHaveLength(0);
  });

  it('rolls back the whole batch when the track does not exist', () => {
    expect(() =>
      apply(emptyDocument(), [
        { type: 'insert_clip', track_id: 'trk_missing', asset_id: 'ast_1', at_ticks: 0, duration_ticks: 1 },
      ]),
    ).toThrow(BatchRolledBackError);
  });
});

describe('applyBatch — delete_elements', () => {
  it('removes matching elements across every track', () => {
    const document = withClip(emptyDocument());
    const result = apply(document, [{ type: 'delete_elements', element_ids: ['el_clip'] }]);
    expect(result.tracks.flatMap((track) => track.elements)).toHaveLength(0);
  });
});

describe('applyBatch — move_elements', () => {
  it('shifts start_ticks by delta_ticks', () => {
    const document = withClip(emptyDocument());
    const result = apply(document, [
      { type: 'move_elements', element_ids: ['el_clip'], delta_ticks: TICKS_PER_SECOND },
    ]);
    expect(result.tracks[0]!.elements[0]!.start_ticks).toBe(TICKS_PER_SECOND);
  });

  it('clamps start_ticks at zero', () => {
    const document = withClip(emptyDocument());
    const result = apply(document, [
      { type: 'move_elements', element_ids: ['el_clip'], delta_ticks: -10 * TICKS_PER_SECOND },
    ]);
    expect(result.tracks[0]!.elements[0]!.start_ticks).toBe(0);
  });

  it('moves the element to another track of the same kind when track_id is given', () => {
    const document = withClip(emptyDocument());
    const result = apply(document, [
      { type: 'add_track', kind: 'video', track_id: 'trk_pip' },
      { type: 'move_elements', element_ids: ['el_clip'], delta_ticks: 0, track_id: 'trk_pip' },
    ]);
    const videoTrack = result.tracks.find((track) => track.id === 'trk_video')!;
    const pipTrack = result.tracks.find((track) => track.id === 'trk_pip')!;
    expect(videoTrack.elements).toHaveLength(0);
    expect(pipTrack.elements).toHaveLength(1);
    expect(pipTrack.elements[0]!.track_id).toBe('trk_pip');
  });

  it('rejects moving an element to a track of a different kind', () => {
    const document = withClip(emptyDocument());
    expect(() =>
      apply(document, [
        { type: 'move_elements', element_ids: ['el_clip'], delta_ticks: 0, track_id: 'trk_overlay' },
      ]),
    ).toThrow(BatchRolledBackError);
  });

  it('rolls back when the element does not exist', () => {
    expect(() =>
      apply(emptyDocument(), [{ type: 'move_elements', element_ids: ['el_missing'], delta_ticks: 1 }]),
    ).toThrow(BatchRolledBackError);
  });
});

describe('applyBatch — trim_element', () => {
  it('updates start/duration/source bounds together', () => {
    const document = withClip(emptyDocument());
    const result = apply(document, [
      {
        type: 'trim_element',
        element_id: 'el_clip',
        start_ticks: TICKS_PER_SECOND,
        duration_ticks: TICKS_PER_SECOND,
        source_in_ticks: TICKS_PER_SECOND,
        source_out_ticks: 2 * TICKS_PER_SECOND,
      },
    ]);
    const clip = result.tracks[0]!.elements[0]!;
    expect(clip.start_ticks).toBe(TICKS_PER_SECOND);
    expect(clip.duration_ticks).toBe(TICKS_PER_SECOND);
    expect(clip.source_in_ticks).toBe(TICKS_PER_SECOND);
    expect(clip.source_out_ticks).toBe(2 * TICKS_PER_SECOND);
  });
});

describe('applyBatch — split_element', () => {
  it('splits into two elements with matching source ticks', () => {
    const document = withClip(emptyDocument());
    const splitAt = Math.round(1.5 * TICKS_PER_SECOND);
    const result = apply(document, [{ type: 'split_element', element_id: 'el_clip', at_ticks: splitAt }]);
    const [left, right] = result.tracks[0]!.elements;
    expect(left!.start_ticks).toBe(0);
    expect(left!.duration_ticks).toBe(splitAt);
    expect(left!.source_out_ticks).toBe(splitAt);
    expect(right!.start_ticks).toBe(splitAt);
    expect(right!.duration_ticks).toBe(2 * TICKS_PER_SECOND - splitAt);
    expect(right!.source_in_ticks).toBe(splitAt);
    expect(right!.id).not.toBe(left!.id);
  });

  it('rolls back a split point outside the element', () => {
    const document = withClip(emptyDocument());
    expect(() => apply(document, [{ type: 'split_element', element_id: 'el_clip', at_ticks: 0 }])).toThrow(
      BatchRolledBackError,
    );
    expect(() =>
      apply(document, [{ type: 'split_element', element_id: 'el_clip', at_ticks: 2 * TICKS_PER_SECOND }]),
    ).toThrow(BatchRolledBackError);
  });
});

describe('applyBatch — volume / speed', () => {
  it('sets volume and speed independently', () => {
    const document = withClip(emptyDocument());
    const result = apply(document, [
      { type: 'set_clip_volume', element_id: 'el_clip', volume_millipercent: 50_000 },
      { type: 'set_clip_speed', element_id: 'el_clip', speed_millipercent: 200_000 },
    ]);
    const clip = result.tracks[0]!.elements[0]!;
    expect(clip.volume_millipercent).toBe(50_000);
    expect(clip.speed_millipercent).toBe(200_000);
  });
});

describe('applyBatch — captions', () => {
  it('inserts a caption with a default language', () => {
    const result = apply(emptyDocument(), [
      {
        type: 'insert_caption',
        track_id: 'trk_caption',
        at_ticks: 0,
        duration_ticks: TICKS_PER_SECOND,
        text: 'hello',
      },
    ]);
    const caption = result.tracks.find((track) => track.kind === 'caption')!.elements[0]!;
    expect(caption.text).toBe('hello');
    expect(caption.caption_language).toBe('zh-CN');
  });

  it('updates only the given caption fields', () => {
    const inserted = apply(emptyDocument(), [
      {
        type: 'insert_caption',
        track_id: 'trk_caption',
        at_ticks: 0,
        duration_ticks: TICKS_PER_SECOND,
        text: 'hello',
        element_id: 'el_cap',
      },
    ]);
    const result = apply(inserted, [{ type: 'update_caption', element_id: 'el_cap', text: 'updated' }]);
    const caption = result.tracks.find((track) => track.kind === 'caption')!.elements[0]!;
    expect(caption.text).toBe('updated');
    expect(caption.start_ticks).toBe(0);
  });

  it('rejects updating a non-caption element as a caption', () => {
    const document = withClip(emptyDocument());
    expect(() => apply(document, [{ type: 'update_caption', element_id: 'el_clip', text: 'x' }])).toThrow(
      BatchRolledBackError,
    );
  });
});

describe('applyBatch — canvas / brand overlay', () => {
  it('updates canvas dimensions and fps', () => {
    const result = apply(emptyDocument(), [
      { type: 'set_canvas', width: 1920, height: 1080, fps_num: 60, fps_den: 1 },
    ]);
    expect(result.canvas).toEqual({ width: 1920, height: 1080, fps_num: 60, fps_den: 1 });
  });

  it('sets and clears the brand overlay', () => {
    const overlay = { asset_id: 'ast_brand', x_milli: 10, y_milli: 10, width_milli: 200 };
    const withOverlay = apply(emptyDocument(), [{ type: 'set_brand_overlay', overlay }]);
    expect(withOverlay.brand_overlay).toEqual(overlay);
    const cleared = apply(withOverlay, [{ type: 'set_brand_overlay', overlay: null }]);
    expect(cleared.brand_overlay).toBeNull();
  });
});

describe('applyBatch — whole-batch rollback', () => {
  it('leaves the original document unchanged when a later command fails', () => {
    const document = withClip(emptyDocument());
    const before = cloneDocument(document);
    expect(() =>
      apply(document, [
        { type: 'set_clip_volume', element_id: 'el_clip', volume_millipercent: 50_000 },
        { type: 'delete_elements', element_ids: ['does_not_matter'] },
        { type: 'move_elements', element_ids: ['el_missing'], delta_ticks: 1 },
      ]),
    ).toThrow(BatchRolledBackError);
    expect(document).toEqual(before);
  });
});

describe('applyBatch — effects', () => {
  it('appends an effect and keeps existing ones', () => {
    const result = apply(withClip(emptyDocument()), [
      { type: 'add_effect', element_id: 'el_clip', effect: { type: 'blur', params: { intensity: 20 } } },
      { type: 'add_effect', element_id: 'el_clip', effect: { type: 'grayscale', params: { amount: 100 } } },
    ]);
    const element = result.tracks.flatMap((track) => track.elements).find((item) => item.id === 'el_clip')!;
    expect(element.effects).toEqual([
      { type: 'blur', params: { intensity: 20 } },
      { type: 'grayscale', params: { amount: 100 } },
    ]);
  });

  it('rejects an effect type outside the confirmed-working allowlist', () => {
    expect(() =>
      apply(withClip(emptyDocument()), [
        { type: 'add_effect', element_id: 'el_clip', effect: { type: 'sepia' as never, params: {} } },
      ]),
    ).toThrow(BatchRolledBackError);
  });

  it('caps the number of effects per element', () => {
    const commands: EditCommand[] = Array.from({ length: 9 }, () => ({
      type: 'add_effect' as const,
      element_id: 'el_clip',
      effect: { type: 'brightness' as const, params: { amount: 110 } },
    }));
    expect(() => apply(withClip(emptyDocument()), commands)).toThrow(BatchRolledBackError);
  });

  it('removes an effect by index', () => {
    const withEffects = apply(withClip(emptyDocument()), [
      { type: 'add_effect', element_id: 'el_clip', effect: { type: 'blur', params: { intensity: 20 } } },
      { type: 'add_effect', element_id: 'el_clip', effect: { type: 'contrast', params: { amount: 120 } } },
    ]);
    const result = applyBatch(
      withEffects,
      [{ type: 'remove_effect', element_id: 'el_clip', effect_index: 0 }],
      new Set(['ast_1']),
    );
    const element = result.tracks.flatMap((track) => track.elements).find((item) => item.id === 'el_clip')!;
    expect(element.effects).toEqual([{ type: 'contrast', params: { amount: 120 } }]);
  });

  it('rejects an out-of-range effect index', () => {
    expect(() =>
      apply(withClip(emptyDocument()), [
        { type: 'remove_effect', element_id: 'el_clip', effect_index: 0 },
      ]),
    ).toThrow(BatchRolledBackError);
  });

  it('merges params without dropping untouched keys', () => {
    const withEffect = apply(withClip(emptyDocument()), [
      { type: 'add_effect', element_id: 'el_clip', effect: { type: 'blur', params: { intensity: 20, extra: 1 } } },
    ]);
    const result = applyBatch(
      withEffect,
      [{ type: 'update_effect_params', element_id: 'el_clip', effect_index: 0, params: { intensity: 40 } }],
      new Set(['ast_1']),
    );
    const element = result.tracks.flatMap((track) => track.elements).find((item) => item.id === 'el_clip')!;
    expect(element.effects[0]!.params).toEqual({ intensity: 40, extra: 1 });
  });
});

describe('applyBatch — clip mask', () => {
  it('sets and clears a mask', () => {
    const mask = { shape: 'ellipse' as const, x_milli: 100, y_milli: 100, width_milli: 800, height_milli: 800, feather_millipercent: 10_000 };
    const withMask = apply(withClip(emptyDocument()), [
      { type: 'set_clip_mask', element_id: 'el_clip', mask },
    ]);
    let element = withMask.tracks.flatMap((track) => track.elements).find((item) => item.id === 'el_clip')!;
    expect(element.mask).toEqual(mask);

    const cleared = applyBatch(
      withMask,
      [{ type: 'set_clip_mask', element_id: 'el_clip', mask: null }],
      new Set(['ast_1']),
    );
    element = cleared.tracks.flatMap((track) => track.elements).find((item) => item.id === 'el_clip')!;
    expect(element.mask).toBeNull();
  });

  it('rejects an unsupported mask shape', () => {
    expect(() =>
      apply(withClip(emptyDocument()), [
        {
          type: 'set_clip_mask',
          element_id: 'el_clip',
          mask: {
            shape: 'star' as never,
            x_milli: 0,
            y_milli: 0,
            width_milli: 100,
            height_milli: 100,
            feather_millipercent: 0,
          },
        },
      ]),
    ).toThrow(BatchRolledBackError);
  });
});

describe('applyBatch — keyframes', () => {
  it('inserts keyframes sorted by tick regardless of insertion order', () => {
    const result = apply(withClip(emptyDocument()), [
      { type: 'set_keyframe', element_id: 'el_clip', property: 'opacity', at_ticks: 2 * TICKS_PER_SECOND, value: 100_000 },
      { type: 'set_keyframe', element_id: 'el_clip', property: 'opacity', at_ticks: 0, value: 0 },
    ]);
    const element = result.tracks.flatMap((track) => track.elements).find((item) => item.id === 'el_clip')!;
    expect(element.animations.channels.opacity!.points.map((point) => point.at_ticks)).toEqual([
      0,
      2 * TICKS_PER_SECOND,
    ]);
  });

  it('replaces an existing point at the same tick rather than duplicating it', () => {
    const result = apply(withClip(emptyDocument()), [
      { type: 'set_keyframe', element_id: 'el_clip', property: 'opacity', at_ticks: 0, value: 10_000 },
      { type: 'set_keyframe', element_id: 'el_clip', property: 'opacity', at_ticks: 0, value: 90_000 },
    ]);
    const element = result.tracks.flatMap((track) => track.elements).find((item) => item.id === 'el_clip')!;
    expect(element.animations.channels.opacity!.points).toEqual([
      { at_ticks: 0, value: 90_000, easing: 'linear' },
    ]);
  });

  it('rejects an unsupported property', () => {
    expect(() =>
      apply(withClip(emptyDocument()), [
        { type: 'set_keyframe', element_id: 'el_clip', property: 'color' as never, at_ticks: 0, value: 0 },
      ]),
    ).toThrow(BatchRolledBackError);
  });

  it('rejects a value outside the property range', () => {
    expect(() =>
      apply(withClip(emptyDocument()), [
        { type: 'set_keyframe', element_id: 'el_clip', property: 'opacity', at_ticks: 0, value: 999_999 },
      ]),
    ).toThrow(BatchRolledBackError);
  });

  it('deletes a keyframe at an exact tick and rejects deleting a tick with none', () => {
    const withPoint = apply(withClip(emptyDocument()), [
      { type: 'set_keyframe', element_id: 'el_clip', property: 'opacity', at_ticks: 0, value: 50_000 },
    ]);
    const cleared = applyBatch(
      withPoint,
      [{ type: 'delete_keyframe', element_id: 'el_clip', property: 'opacity', at_ticks: 0 }],
      new Set(['ast_1']),
    );
    expect(cleared.tracks.flatMap((t) => t.elements)[0]!.animations.channels.opacity!.points).toEqual([]);
    expect(() =>
      applyBatch(
        cleared,
        [{ type: 'delete_keyframe', element_id: 'el_clip', property: 'opacity', at_ticks: 0 }],
        new Set(['ast_1']),
      ),
    ).toThrow(BatchRolledBackError);
  });

  it('clears a whole channel', () => {
    const withPoints = apply(withClip(emptyDocument()), [
      { type: 'set_keyframe', element_id: 'el_clip', property: 'opacity', at_ticks: 0, value: 0 },
      { type: 'set_keyframe', element_id: 'el_clip', property: 'opacity', at_ticks: 1000, value: 100_000 },
    ]);
    const cleared = applyBatch(
      withPoints,
      [{ type: 'clear_keyframes', element_id: 'el_clip', property: 'opacity' }],
      new Set(['ast_1']),
    );
    const element = cleared.tracks.flatMap((track) => track.elements).find((item) => item.id === 'el_clip')!;
    expect(element.animations.channels.opacity).toBeUndefined();
  });

  it('does not alias keyframe channels between split halves', () => {
    const withPoint = apply(withClip(emptyDocument()), [
      { type: 'set_keyframe', element_id: 'el_clip', property: 'opacity', at_ticks: 0, value: 50_000 },
      { type: 'split_element', element_id: 'el_clip', at_ticks: TICKS_PER_SECOND },
    ]);
    const elements = withPoint.tracks.flatMap((track) => track.elements);
    const right = elements.find((item) => item.id !== 'el_clip')!;
    const withMoreKeyframes = applyBatch(
      withPoint,
      [{ type: 'set_keyframe', element_id: right.id, property: 'opacity', at_ticks: 500, value: 20_000 }],
      new Set(['ast_1']),
    );
    const left = withMoreKeyframes.tracks.flatMap((track) => track.elements).find((item) => item.id === 'el_clip')!;
    expect(left.animations.channels.opacity!.points).toHaveLength(1);
  });

  it('defaults easing to linear when omitted and stores an explicit easing when given', () => {
    const result = apply(withClip(emptyDocument()), [
      { type: 'set_keyframe', element_id: 'el_clip', property: 'opacity', at_ticks: 0, value: 0 },
      { type: 'set_keyframe', element_id: 'el_clip', property: 'opacity', at_ticks: 1000, value: 100_000, easing: 'ease_in' },
    ]);
    const points = result.tracks.flatMap((track) => track.elements)[0]!.animations.channels.opacity!.points;
    expect(points[0]!.easing).toBe('linear');
    expect(points[1]!.easing).toBe('ease_in');
  });

  it('rejects an unsupported easing type', () => {
    expect(() =>
      apply(withClip(emptyDocument()), [
        { type: 'set_keyframe', element_id: 'el_clip', property: 'opacity', at_ticks: 0, value: 0, easing: 'bounce' as never },
      ]),
    ).toThrow(BatchRolledBackError);
  });

  it('accepts volume as an animatable property within its set_clip_volume-matching range', () => {
    const result = apply(withClip(emptyDocument()), [
      { type: 'set_keyframe', element_id: 'el_clip', property: 'volume', at_ticks: 0, value: 150_000 },
    ]);
    const points = result.tracks.flatMap((track) => track.elements)[0]!.animations.channels.volume!.points;
    expect(points).toEqual([{ at_ticks: 0, value: 150_000, easing: 'linear' }]);
  });

  it('rejects a volume keyframe value outside 0-200000', () => {
    expect(() =>
      apply(withClip(emptyDocument()), [
        { type: 'set_keyframe', element_id: 'el_clip', property: 'volume', at_ticks: 0, value: 250_000 },
      ]),
    ).toThrow(BatchRolledBackError);
  });
});

describe('applyBatch — markers', () => {
  it('adds a marker with an explicit id and label', () => {
    const result = apply(emptyDocument(), [
      { type: 'add_marker', at_ticks: 1000, label: '开场', marker_id: 'mrk_1' },
    ]);
    expect(result.markers).toEqual([{ id: 'mrk_1', at_ticks: 1000, label: '开场' }]);
  });

  it('rejects adding a marker whose id already exists', () => {
    const withMarker = apply(emptyDocument(), [{ type: 'add_marker', at_ticks: 0, marker_id: 'mrk_1' }]);
    expect(() => apply(withMarker, [{ type: 'add_marker', at_ticks: 1000, marker_id: 'mrk_1' }])).toThrow(
      BatchRolledBackError,
    );
  });

  it('updates a marker in place and rejects updating a marker that does not exist', () => {
    const withMarker = apply(emptyDocument(), [
      { type: 'add_marker', at_ticks: 0, label: 'old', marker_id: 'mrk_1' },
    ]);
    const updated = apply(withMarker, [{ type: 'update_marker', marker_id: 'mrk_1', at_ticks: 500, label: 'new' }]);
    expect(updated.markers).toEqual([{ id: 'mrk_1', at_ticks: 500, label: 'new' }]);
    expect(() => apply(withMarker, [{ type: 'update_marker', marker_id: 'mrk_missing', label: 'x' }])).toThrow(
      BatchRolledBackError,
    );
  });

  it('removes a marker and rejects removing one that does not exist', () => {
    const withMarker = apply(emptyDocument(), [{ type: 'add_marker', at_ticks: 0, marker_id: 'mrk_1' }]);
    const removed = apply(withMarker, [{ type: 'remove_marker', marker_id: 'mrk_1' }]);
    expect(removed.markers).toEqual([]);
    expect(() => apply(withMarker, [{ type: 'remove_marker', marker_id: 'mrk_missing' }])).toThrow(
      BatchRolledBackError,
    );
  });
});

describe('applyBatch — stickers and transitions', () => {
  it('inserts a sticker element via element_type, defaulting to clip', () => {
    const result = apply(emptyDocument(), [
      {
        type: 'insert_clip',
        track_id: 'trk_video',
        asset_id: 'ast_1',
        at_ticks: 0,
        duration_ticks: TICKS_PER_SECOND,
        element_id: 'el_sticker',
        element_type: 'sticker',
      },
    ]);
    const element = result.tracks.flatMap((track) => track.elements).find((item) => item.id === 'el_sticker')!;
    expect(element.type).toBe('sticker');

    const plain = apply(emptyDocument(), [
      { type: 'insert_clip', track_id: 'trk_video', asset_id: 'ast_1', at_ticks: 0, duration_ticks: TICKS_PER_SECOND, element_id: 'el_plain' },
    ]);
    expect(plain.tracks.flatMap((t) => t.elements).find((el) => el.id === 'el_plain')!.type).toBe('clip');
  });

  it('rejects an unsupported element_type', () => {
    expect(() =>
      apply(emptyDocument(), [
        {
          type: 'insert_clip',
          track_id: 'trk_video',
          asset_id: 'ast_1',
          at_ticks: 0,
          duration_ticks: TICKS_PER_SECOND,
          element_type: 'shape' as never,
        },
      ]),
    ).toThrow(BatchRolledBackError);
  });

  it('sets a transition on each edge independently and clears it with null', () => {
    const result = apply(withClip(emptyDocument(), { duration_ticks: 2 * TICKS_PER_SECOND }), [
      {
        type: 'set_transition',
        element_id: 'el_clip',
        edge: 'out',
        transition: { type: 'crossfade', duration_ticks: TICKS_PER_SECOND },
      },
    ]);
    let element = result.tracks.flatMap((t) => t.elements).find((el) => el.id === 'el_clip')!;
    expect(element.transition_out).toEqual({ type: 'crossfade', duration_ticks: TICKS_PER_SECOND });
    expect(element.transition_in).toBeNull();

    const cleared = applyBatch(
      result,
      [{ type: 'set_transition', element_id: 'el_clip', edge: 'out', transition: null }],
      new Set(['ast_1']),
    );
    element = cleared.tracks.flatMap((t) => t.elements).find((el) => el.id === 'el_clip')!;
    expect(element.transition_out).toBeNull();
  });

  it('rejects an unsupported transition type', () => {
    expect(() =>
      apply(withClip(emptyDocument()), [
        {
          type: 'set_transition',
          element_id: 'el_clip',
          edge: 'out',
          transition: { type: 'wipe' as never, duration_ticks: TICKS_PER_SECOND },
        },
      ]),
    ).toThrow(BatchRolledBackError);
  });

  it('rejects a transition longer than the element itself', () => {
    expect(() =>
      apply(withClip(emptyDocument(), { duration_ticks: TICKS_PER_SECOND }), [
        {
          type: 'set_transition',
          element_id: 'el_clip',
          edge: 'out',
          transition: { type: 'crossfade', duration_ticks: 2 * TICKS_PER_SECOND },
        },
      ]),
    ).toThrow(BatchRolledBackError);
  });

  it('moves transition_out to the right half and keeps transition_in on the left half after a split', () => {
    const withTransitions = apply(withClip(emptyDocument(), { duration_ticks: 4 * TICKS_PER_SECOND }), [
      {
        type: 'set_transition',
        element_id: 'el_clip',
        edge: 'in',
        transition: { type: 'crossfade', duration_ticks: TICKS_PER_SECOND },
      },
      {
        type: 'set_transition',
        element_id: 'el_clip',
        edge: 'out',
        transition: { type: 'dip_to_black', duration_ticks: TICKS_PER_SECOND },
      },
    ]);
    const result = applyBatch(
      withTransitions,
      [{ type: 'split_element', element_id: 'el_clip', at_ticks: 2 * TICKS_PER_SECOND }],
      new Set(['ast_1']),
    );
    const elements = result.tracks.flatMap((t) => t.elements);
    const left = elements.find((el) => el.id === 'el_clip')!;
    const right = elements.find((el) => el.id !== 'el_clip')!;
    expect(left.transition_in).toEqual({ type: 'crossfade', duration_ticks: TICKS_PER_SECOND });
    expect(left.transition_out).toBeNull();
    expect(right.transition_in).toBeNull();
    expect(right.transition_out).toEqual({ type: 'dip_to_black', duration_ticks: TICKS_PER_SECOND });
  });
});
