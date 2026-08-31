import { afterEach, describe, expect, it, vi } from 'vitest';

import { sha256Hex } from './sha256';

const EMPTY = 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855';
const ABC = 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad';
const PNG_1X1 = 'c414cd0e204de974f73753c7e28d7638e7b3691bb8b1a2bab6b25bb7fed7ce77';

const png = Uint8Array.from(
  atob('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=='),
  (char) => char.charCodeAt(0),
);

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('sha256Hex', () => {
  it('uses crypto.subtle when the context is secure', async () => {
    const digest = new Uint8Array(32);
    digest[31] = 0xab;
    vi.stubGlobal('crypto', {
      subtle: {
        digest: async () => digest.buffer,
      },
    });
    expect(await sha256Hex(new ArrayBuffer(0))).toBe(`${'00'.repeat(31)}ab`);
  });

  it('falls back to software SHA-256 on a non-secure HTTP origin', async () => {
    vi.stubGlobal('crypto', {});
    expect(await sha256Hex(new ArrayBuffer(0))).toBe(EMPTY);
    expect(await sha256Hex(new TextEncoder().encode('abc').buffer)).toBe(ABC);
    expect(await sha256Hex(png.buffer)).toBe(PNG_1X1);
  });
});
