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
  it('sends an image-creation job notification into the studio with that job id', () => {
    expect(targetHref(jobNotification())).toBe(
      '/create/new?mode=image_creation&draftId=drf_1&jobId=job_new',
    );
  });

  it('falls back to the job page when the image job has no draft', () => {
    expect(
      targetHref(
        jobNotification({
          payload: { operation: 'text_to_image', draft_id: undefined },
        }),
      ),
    ).toBe('/jobs/job_new');
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
