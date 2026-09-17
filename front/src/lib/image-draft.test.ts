import { describe, expect, it } from 'vitest';

import { imageCreationStudioHref, isImageCreationOperation } from './image-draft';

describe('isImageCreationOperation', () => {
  it('accepts the two image operations', () => {
    expect(isImageCreationOperation('text_to_image')).toBe(true);
    expect(isImageCreationOperation('image_to_image')).toBe(true);
    expect(isImageCreationOperation('text_to_video')).toBe(false);
  });
});

describe('imageCreationStudioHref', () => {
  it('resumes a draft card without a specific job', () => {
    expect(imageCreationStudioHref('drf_1')).toBe('/create/new?mode=image_creation&draftId=drf_1');
  });

  it('pins a notification to the job it is about', () => {
    expect(imageCreationStudioHref('drf_1', 'job_retry')).toBe(
      '/create/new?mode=image_creation&draftId=drf_1&jobId=job_retry',
    );
  });
});
