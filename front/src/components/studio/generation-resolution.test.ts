import { describe, expect, it } from 'vitest';

import { adaptStudioResolution } from './generation-resolution';

describe('adaptStudioResolution', () => {
  const h3 = ['720p', '2K'] as const;
  const seedance = ['480p', '720p', '1080p'] as const;

  it('keeps an exact tier the model already supports', () => {
    expect(adaptStudioResolution('2K', h3)).toEqual({ studioTier: '2K', kind: 'exact' });
  });

  it('downgrades H3 + 1080p to 720p, never up to 2K', () => {
    expect(adaptStudioResolution('1080p', h3)).toEqual({
      studioTier: '720p',
      kind: 'downgrade',
    });
  });

  it('downgrades Seedance + 2K to 1080p', () => {
    expect(adaptStudioResolution('2K', seedance)).toEqual({
      studioTier: '1080p',
      kind: 'downgrade',
    });
  });

  it('falls back to the model lowest tier when nothing is at or below the request', () => {
    expect(adaptStudioResolution('480p', h3)).toEqual({
      studioTier: '720p',
      kind: 'upgrade',
    });
  });

  it('passes the request through when the model is unrestricted', () => {
    expect(adaptStudioResolution('1080p', null)).toEqual({
      studioTier: '1080p',
      kind: 'exact',
    });
  });
});
