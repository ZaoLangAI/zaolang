import { describe, expect, it } from 'vitest';

import {
  durationFromVersion,
  promptFromVersion,
  videoAssetKindFromVersion,
} from './generation-version-select';

describe('promptFromVersion', () => {
  it('returns the submitted prompt, trimmed', () => {
    expect(promptFromVersion({ prompt: '  润色后的镜头  ' })).toBe('润色后的镜头');
  });

  it('ignores a blank or missing prompt so the studio keeps its current field', () => {
    expect(promptFromVersion({ prompt: '   ' })).toBeNull();
    expect(promptFromVersion({ prompt: null })).toBeNull();
    expect(promptFromVersion({})).toBeNull();
  });
});

describe('durationFromVersion', () => {
  it('returns a duration the studio actually offers', () => {
    expect(durationFromVersion({ duration_seconds: 8 }, [4, 8, 12])).toBe(8);
  });

  it('ignores a duration outside the studio allowlist', () => {
    expect(durationFromVersion({ duration_seconds: 30 }, [4, 8, 12])).toBeNull();
    expect(durationFromVersion({ duration_seconds: null }, [8])).toBeNull();
  });
});

describe('videoAssetKindFromVersion', () => {
  const kinds = ['general', 'character_action', 'cover_video'] as const;

  it('returns a kind the studio knows', () => {
    expect(videoAssetKindFromVersion({ video_asset_kind: 'cover_video' }, kinds)).toBe(
      'cover_video',
    );
  });

  it('ignores an unknown or empty kind', () => {
    expect(videoAssetKindFromVersion({ video_asset_kind: 'other' }, kinds)).toBeNull();
    expect(videoAssetKindFromVersion({ video_asset_kind: null }, kinds)).toBeNull();
  });
});
