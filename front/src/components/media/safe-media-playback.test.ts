import { describe, expect, it, vi } from 'vitest';

import {
  delayUntilSignedUrlRefresh,
  isNotAllowedError,
  isPlayAbortError,
  mediaObjectKey,
  pauseMedia,
  playMedia,
  SIGNED_URL_REFRESH_MARGIN_MS,
  signedUrlExpiresAt,
} from './safe-media-playback';

function abortError(): DOMException {
  return new DOMException('The play() request was interrupted by a call to pause().', 'AbortError');
}

function mockMedia(overrides: Partial<HTMLMediaElement> = {}) {
  return {
    paused: true,
    play: vi.fn(),
    pause: vi.fn(),
    ...overrides,
  } as unknown as HTMLMediaElement;
}

describe('isPlayAbortError / isNotAllowedError', () => {
  it('recognises DOMException AbortError', () => {
    expect(isPlayAbortError(abortError())).toBe(true);
    expect(isPlayAbortError(new Error('nope'))).toBe(false);
  });

  it('recognises a plain Error named AbortError', () => {
    const error = new Error('aborted');
    error.name = 'AbortError';
    expect(isPlayAbortError(error)).toBe(true);
  });

  it('recognises NotAllowedError', () => {
    expect(isNotAllowedError(new DOMException('blocked', 'NotAllowedError'))).toBe(true);
    expect(isNotAllowedError(abortError())).toBe(false);
  });
});

describe('playMedia', () => {
  it('swallows AbortError from play()', async () => {
    const el = mockMedia({ play: vi.fn().mockRejectedValue(abortError()) });
    await expect(playMedia(el)).resolves.toBeUndefined();
  });

  it('re-throws other play() failures', async () => {
    const el = mockMedia({
      play: vi.fn().mockRejectedValue(new DOMException('blocked', 'NotAllowedError')),
    });
    await expect(playMedia(el)).rejects.toMatchObject({ name: 'NotAllowedError' });
  });

  it('resolves when play() succeeds', async () => {
    const el = mockMedia({ play: vi.fn().mockResolvedValue(undefined) });
    await playMedia(el);
    expect(el.play).toHaveBeenCalledOnce();
  });
});

describe('pauseMedia', () => {
  it('waits for an in-flight play() before pausing', async () => {
    const order: string[] = [];
    let release!: () => void;
    const playInFlight = new Promise<void>((resolve) => {
      release = resolve;
    }).then(() => {
      order.push('play');
    });
    const el = mockMedia({
      pause: vi.fn(() => {
        order.push('pause');
      }),
    });

    const pausing = pauseMedia(el, playInFlight);
    expect(order).toEqual([]);
    release();
    await pausing;
    expect(order).toEqual(['play', 'pause']);
  });

  it('still pauses when the in-flight play() rejects', async () => {
    const el = mockMedia();
    await pauseMedia(el, Promise.reject(abortError()));
    expect(el.pause).toHaveBeenCalledOnce();
  });

  it('pauses immediately when nothing is in flight', async () => {
    const el = mockMedia();
    await pauseMedia(el, null);
    expect(el.pause).toHaveBeenCalledOnce();
  });
});

describe('mediaObjectKey', () => {
  it('strips the signature query so two signs of one object match', () => {
    const a =
      'http://localhost:9000/zaolang/out/clip.mp4?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Signature=aaa';
    const b =
      'http://localhost:9000/zaolang/out/clip.mp4?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Signature=bbb';
    expect(mediaObjectKey(a)).toBe(mediaObjectKey(b));
    expect(mediaObjectKey(a)).toBe('http://localhost:9000/zaolang/out/clip.mp4');
  });

  it('falls back to the pre-query string for non-URLs', () => {
    expect(mediaObjectKey('not a url?sig=1')).toBe('not a url');
  });
});

describe('signedUrlExpiresAt', () => {
  const sample =
    'http://localhost:9000/zaolang/out/clip.mp4?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Date=20260814T060000Z&X-Amz-Expires=900&X-Amz-Signature=abc';

  it('adds X-Amz-Expires seconds to X-Amz-Date', () => {
    const issued = Date.UTC(2026, 7, 14, 6, 0, 0);
    expect(signedUrlExpiresAt(sample)).toBe(issued + 900_000);
  });

  it('returns null when the URL is not SigV4', () => {
    expect(signedUrlExpiresAt('http://localhost:9000/zaolang/out/clip.mp4')).toBeNull();
  });

  it('schedules a refresh one minute before expiry', () => {
    const issued = Date.UTC(2026, 7, 14, 6, 0, 0);
    const now = issued + 100_000;
    expect(delayUntilSignedUrlRefresh(sample, now)).toBe(900_000 - 100_000 - SIGNED_URL_REFRESH_MARGIN_MS);
  });

  it('returns 0 when the URL is already inside the refresh margin', () => {
    const issued = Date.UTC(2026, 7, 14, 6, 0, 0);
    const now = issued + 880_000;
    expect(delayUntilSignedUrlRefresh(sample, now)).toBe(0);
  });
});
