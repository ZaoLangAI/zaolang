import { afterEach, describe, expect, it, vi } from 'vitest';

import { randomUuid } from './random-id';

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('randomUuid', () => {
  it('uses crypto.randomUUID when the context is secure', () => {
    vi.stubGlobal('crypto', {
      randomUUID: () => 'aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee',
    });
    expect(randomUuid()).toBe('aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee');
  });

  it('falls back to getRandomValues on a non-secure HTTP origin', () => {
    let seed = 0;
    vi.stubGlobal('crypto', {
      getRandomValues: (target: Uint8Array) => {
        for (let i = 0; i < target.length; i += 1) target[i] = (seed + i) & 0xff;
        seed += 1;
        return target;
      },
    });
    const id = randomUuid();
    expect(id).toMatch(UUID_RE);
    expect(id).not.toBe(randomUuid());
  });

  it('still produces a v4 UUID when Web Crypto is missing entirely', () => {
    vi.stubGlobal('crypto', undefined);
    expect(randomUuid()).toMatch(UUID_RE);
  });
});
