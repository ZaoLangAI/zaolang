import { describe, expect, it } from 'vitest';

import {
  assetJobHref,
  assetWorkspaceHref,
  imageDraftHref,
  isRetiredImageJob,
} from './asset-job-href';

describe('assetWorkspaceHref', () => {
  it('prefers the card the output filed into, with the targeted look', () => {
    expect(
      assetWorkspaceHref({
        linked_character_id: 'sk_char',
        target_character_id: 'sk_other',
        target_variant_id: 'var_1',
      }),
    ).toBe('/create/characters/sk_char?look=var_1');
  });

  it('falls back to the requested target before write-back', () => {
    expect(assetWorkspaceHref({ target_scene_id: 'sk_scene' })).toBe('/create/scenes/sk_scene');
    expect(assetWorkspaceHref({ target_prop_id: 'sk_prop', target_variant_id: 'var_x' })).toBe(
      '/create/props/sk_prop?look=var_x',
    );
  });

  it('is null for an image that names no card', () => {
    expect(assetWorkspaceHref({})).toBeNull();
    expect(assetWorkspaceHref({ linked_character_id: '', target_scene_id: null })).toBeNull();
  });
});

describe('assetJobHref', () => {
  it('lands on the read-only job page without a card', () => {
    expect(assetJobHref('job_1', {})).toBe('/jobs/job_1');
    expect(assetJobHref('job_1', { linked_prop_id: 'sk_p' })).toBe('/create/props/sk_p');
  });
});

describe('imageDraftHref', () => {
  it('opens the workspace, else the latest job, else the publish form', () => {
    expect(
      imageDraftHref({
        id: 'drf_1',
        latest_job_id: 'job_1',
        params: { target_character_id: 'sk_c' },
      }),
    ).toBe('/create/characters/sk_c');
    expect(imageDraftHref({ id: 'drf_1', latest_job_id: 'job_1', params: {} })).toBe('/jobs/job_1');
    expect(imageDraftHref({ id: 'drf_1', latest_job_id: null, params: null })).toBe(
      '/publish/drf_1',
    );
  });
});

describe('isRetiredImageJob', () => {
  it('flags general, cover and unset image kinds only', () => {
    expect(isRetiredImageJob({ operation: 'text_to_image', asset_kind: 'general' })).toBe(true);
    expect(isRetiredImageJob({ operation: 'image_to_image', asset_kind: 'cover' })).toBe(true);
    expect(isRetiredImageJob({ operation: 'text_to_image', asset_kind: null })).toBe(true);
    expect(isRetiredImageJob({ operation: 'text_to_image', asset_kind: 'prop' })).toBe(false);
    expect(isRetiredImageJob({ operation: 'text_to_video', asset_kind: null })).toBe(false);
  });
});
