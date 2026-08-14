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

  it('moves the element to another track when track_id is given', () => {
    const document = withClip(emptyDocument());
    const result = apply(document, [
      { type: 'move_elements', element_ids: ['el_clip'], delta_ticks: 0, track_id: 'trk_overlay' },
    ]);
    const videoTrack = result.tracks.find((track) => track.id === 'trk_video')!;
    const overlayTrack = result.tracks.find((track) => track.id === 'trk_overlay')!;
    expect(videoTrack.elements).toHaveLength(0);
    expect(overlayTrack.elements).toHaveLength(1);
    expect(overlayTrack.elements[0]!.track_id).toBe('trk_overlay');
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
