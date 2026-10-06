import { describe, expect, it } from 'vitest';

import type { Notification } from '@/lib/api/types';

import { MAX_VISIBLE_TOASTS, targetHref, visibleToasts } from './notification-format';

function jobNotification(
  overrides: Partial<Notification> & { payload?: Notification['payload'] } = {},
): Notification {
  const { payload, ...rest } = overrides;
  return {
    id: 'ntf_1',
    type: 'job_progress',
    title_key: 'notification.job_queued',
    payload: {
      operation: 'image_to_image',
      draft_id: 'drf_1',
      ...payload,
    },
    target_type: 'generation_job',
    target_id: 'job_new',
    read: false,
    created_at: '2026-08-30T00:00:00Z',
    updated_at: '2026-08-30T00:00:00Z',
    ...rest,
  };
}

describe('targetHref', () => {
  it('sends a general image job notification to its read-only job page', () => {
    // The image studio is gone: an old general / cover draft's job is
    // shown (and publishable) on /jobs/{id}.
    expect(targetHref(jobNotification())).toBe('/jobs/job_new');
    expect(
      targetHref(
        jobNotification({
          payload: { operation: 'text_to_image', draft_id: undefined, asset_kind: 'cover' },
        }),
      ),
    ).toBe('/jobs/job_new');
  });

  it('sends an asset image job notification into its card workspace', () => {
    expect(
      targetHref(
        jobNotification({
          payload: {
            operation: 'text_to_image',
            asset_kind: 'character',
            linked_character_id: 'sk_char',
            target_variant_id: 'var_wedding',
          },
        }),
      ),
    ).toBe('/create/characters/sk_char?look=var_wedding');
    expect(
      targetHref(
        jobNotification({
          payload: { operation: 'image_to_image', asset_kind: 'scene', linked_scene_id: 'sk_s' },
        }),
      ),
    ).toBe('/create/scenes/sk_s');
    expect(
      targetHref(
        jobNotification({
          payload: { operation: 'text_to_image', asset_kind: 'prop', linked_prop_id: 'sk_p' },
        }),
      ),
    ).toBe('/create/props/sk_p');
  });

  it('sends a video-creation job notification into the studio with that job id', () => {
    expect(
      targetHref(
        jobNotification({
          payload: { operation: 'text_to_video', draft_id: 'drf_1' },
        }),
      ),
    ).toBe('/create/new?mode=video_creation&draftId=drf_1&jobId=job_new');
  });

  it('falls back to the job page when the video job has no draft', () => {
    expect(
      targetHref(
        jobNotification({
          payload: { operation: 'video_to_video', draft_id: undefined },
        }),
      ),
    ).toBe('/jobs/job_new');
  });

  it('leaves audio jobs on the standalone progress page', () => {
    expect(
      targetHref(
        jobNotification({
          payload: { operation: 'audio_generation', draft_id: 'drf_1' },
        }),
      ),
    ).toBe('/jobs/job_new');
  });
});

describe('visibleToasts', () => {
  it('keeps the newest cards and folds the rest into a count', () => {
    const toasts = Array.from({ length: 10 }, (_, index) => index);
    expect(visibleToasts(toasts)).toEqual({ shown: [7, 8, 9], folded: 7 });
  });

  it('folds nothing while the stack is small', () => {
    expect(visibleToasts([1, 2])).toEqual({ shown: [1, 2], folded: 0 });
    expect(MAX_VISIBLE_TOASTS).toBe(3);
  });
});
