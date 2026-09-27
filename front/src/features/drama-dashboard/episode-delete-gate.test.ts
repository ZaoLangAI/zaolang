import { describe, expect, it } from 'vitest';

import {
  isEpisodeDeleteBlocked,
  isExportRecordDeletable,
  resumeEditorHref,
} from './episode-delete-gate';

describe('isEpisodeDeleteBlocked', () => {
  it('allows delete when the episode has no published output', () => {
    expect(isEpisodeDeleteBlocked({})).toBe(false);
    expect(isEpisodeDeleteBlocked({ exports: [] })).toBe(false);
    expect(
      isEpisodeDeleteBlocked({
        exports: [{ published_work_id: null }, { published_work_id: undefined }],
      }),
    ).toBe(false);
  });

  it('does not treat an unpublished cut as a reason to lock delete', () => {
    expect(
      isEpisodeDeleteBlocked({
        canonicalWorkId: null,
        exports: [{ published_work_id: null }],
      }),
    ).toBe(false);
  });

  it('blocks delete once a canonical work is set', () => {
    expect(isEpisodeDeleteBlocked({ canonicalWorkId: 'w_final' })).toBe(true);
  });

  it('blocks delete when any export is bound to a published work', () => {
    expect(
      isEpisodeDeleteBlocked({
        exports: [{ published_work_id: null }, { published_work_id: 'w_pub' }],
      }),
    ).toBe(true);
  });
});

describe('isExportRecordDeletable', () => {
  it('allows delete for a terminal unpublished export', () => {
    expect(isExportRecordDeletable({ status: 'succeeded' })).toBe(true);
    expect(isExportRecordDeletable({ status: 'failed', published_work_id: null })).toBe(true);
    expect(isExportRecordDeletable({ status: 'cancelled' })).toBe(true);
  });

  it('refuses in-flight or published rows', () => {
    expect(isExportRecordDeletable({ status: 'encoding' })).toBe(false);
    expect(isExportRecordDeletable({ status: 'queued' })).toBe(false);
    expect(isExportRecordDeletable({ status: 'succeeded', published_work_id: 'w_pub' })).toBe(
      false,
    );
  });
});

describe('resumeEditorHref', () => {
  it('is absent when there is no cut to resume', () => {
    expect(resumeEditorHref([])).toBeUndefined();
  });

  it('points at the first existing cut', () => {
    expect(resumeEditorHref([{ id: 'cut_a' }, { id: 'cut_b' }])).toBe('/studio-editor/cut_a');
  });

  it('appends a bindable draft id when one is given', () => {
    expect(resumeEditorHref([{ id: 'cut_a' }], 'drf_1')).toBe('/studio-editor/cut_a?draftId=drf_1');
  });

  it('omits the query when the draft id is empty', () => {
    expect(resumeEditorHref([{ id: 'cut_a' }], null)).toBe('/studio-editor/cut_a');
  });
});
