import { describe, expect, it } from 'vitest';

import { inputRequestRetryMs } from './input-request-retry';

describe('inputRequestRetryMs', () => {
  it('retries 404s at 200ms / 500ms / 1s / 2s and then stays at 2s', () => {
    expect(inputRequestRetryMs({ attempt: 1, isNotFound: true })).toBe(200);
    expect(inputRequestRetryMs({ attempt: 2, isNotFound: true })).toBe(500);
    expect(inputRequestRetryMs({ attempt: 3, isNotFound: true })).toBe(1_000);
    expect(inputRequestRetryMs({ attempt: 4, isNotFound: true })).toBe(2_000);
    expect(inputRequestRetryMs({ attempt: 9, isNotFound: true })).toBe(2_000);
  });

  it('does not wait before the first request', () => {
    expect(inputRequestRetryMs({ attempt: 0, isNotFound: true })).toBe(0);
  });

  it('stops on a non-404 error', () => {
    expect(inputRequestRetryMs({ attempt: 1, isNotFound: false })).toBeNull();
  });

  it('stops after unmount even if the last response was 404', () => {
    expect(inputRequestRetryMs({ attempt: 1, isNotFound: true, cancelled: true })).toBeNull();
  });
});
