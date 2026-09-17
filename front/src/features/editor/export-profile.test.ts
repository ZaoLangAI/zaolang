import { describe, expect, it } from 'vitest';

import { pickDefaultProfileKey } from './export-profile';

const vertical = {
  key: 'douyin_vertical',
  aspect_ratio: '9:16',
  width: 1080,
  height: 1920,
  min_duration_seconds: 5,
  max_duration_seconds: 30,
  max_title_length: 55,
  max_hashtags: 5,
  safe_area_top_pct: 12,
  safe_area_bottom_pct: 22,
  safe_area_right_pct: 18,
  require_ai_disclosure: true,
};

const landscape = {
  key: 'douyin_landscape',
  aspect_ratio: '16:9',
  width: 1920,
  height: 1080,
  min_duration_seconds: 5,
  max_duration_seconds: 30,
  max_title_length: 55,
  max_hashtags: 5,
  safe_area_top_pct: 10,
  safe_area_bottom_pct: 18,
  safe_area_right_pct: 8,
  require_ai_disclosure: true,
};

describe('pickDefaultProfileKey', () => {
  const catalog = [landscape, vertical];

  it('picks the portrait spec for a portrait canvas, ignoring alphabetical order', () => {
    expect(pickDefaultProfileKey(catalog, { width: 1080, height: 1920 }, 'douyin_vertical')).toBe(
      'douyin_vertical',
    );
  });

  it('picks the landscape spec for a landscape canvas', () => {
    expect(pickDefaultProfileKey(catalog, { width: 1920, height: 1080 }, 'douyin_vertical')).toBe(
      'douyin_landscape',
    );
  });

  it('falls back to the catalogue default on a square canvas', () => {
    expect(pickDefaultProfileKey(catalog, { width: 1080, height: 1080 }, 'douyin_vertical')).toBe(
      'douyin_vertical',
    );
  });
});
