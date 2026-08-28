import { beforeEach, describe, expect, it, vi } from 'vitest';

import {
  clearResourceCache,
  dedupedFetch,
  getCached,
  invalidateResource,
  invalidateResourceMatching,
  setCached,
} from './resource-cache';

beforeEach(() => {
  clearResourceCache();
});

describe('getCached / setCached', () => {
  it('returns undefined for a path that was never cached', () => {
    expect(getCached('/v1/me')).toBeUndefined();
  });

  it('returns the last value written for a path', () => {
    setCached('/v1/me', { id: 'u_1' });
    expect(getCached('/v1/me')).toEqual({ id: 'u_1' });
    setCached('/v1/me', { id: 'u_2' });
    expect(getCached('/v1/me')).toEqual({ id: 'u_2' });
  });

  it('keeps separate paths independent', () => {
    setCached('/v1/me', { id: 'u_1' });
    setCached('/v1/collections', { items: [] });
    expect(getCached('/v1/me')).toEqual({ id: 'u_1' });
    expect(getCached('/v1/collections')).toEqual({ items: [] });
  });
});

describe('dedupedFetch', () => {
  it('runs the loader once for concurrent callers of the same path', async () => {
    const loader = vi.fn().mockResolvedValue('result');

    const [first, second] = await Promise.all([
      dedupedFetch('/v1/works', loader),
      dedupedFetch('/v1/works', loader),
    ]);

    expect(loader).toHaveBeenCalledTimes(1);
    expect(first).toBe('result');
    expect(second).toBe('result');
  });

  it('starts a fresh request once the previous one has settled', async () => {
    const loader = vi.fn().mockResolvedValue('result');

    await dedupedFetch('/v1/works', loader);
    await dedupedFetch('/v1/works', loader);

    expect(loader).toHaveBeenCalledTimes(2);
  });

  it('does not cache a rejection — the next call retries', async () => {
    const loader = vi.fn().mockRejectedValueOnce(new Error('boom')).mockResolvedValueOnce('ok');

    await expect(dedupedFetch('/v1/works', loader)).rejects.toThrow('boom');
    await expect(dedupedFetch('/v1/works', loader)).resolves.toBe('ok');
    expect(loader).toHaveBeenCalledTimes(2);
  });

  it('never coalesces different paths', async () => {
    const loader = vi.fn().mockResolvedValue('result');

    await Promise.all([dedupedFetch('/v1/works', loader), dedupedFetch('/v1/collections', loader)]);

    expect(loader).toHaveBeenCalledTimes(2);
  });
});

describe('invalidateResource / invalidateResourceMatching', () => {
  it('drops exactly the requested path', () => {
    setCached('/v1/me', { id: 'u_1' });
    setCached('/v1/collections', { items: [] });

    invalidateResource('/v1/me');

    expect(getCached('/v1/me')).toBeUndefined();
    expect(getCached('/v1/collections')).toEqual({ items: [] });
  });

  it('drops every path matching the predicate', () => {
    setCached('/v1/collections', { items: [1] });
    setCached('/v1/collections/c_1/items', { items: [2] });
    setCached('/v1/me', { id: 'u_1' });

    invalidateResourceMatching((path) => path.startsWith('/v1/collections'));

    expect(getCached('/v1/collections')).toBeUndefined();
    expect(getCached('/v1/collections/c_1/items')).toBeUndefined();
    expect(getCached('/v1/me')).toEqual({ id: 'u_1' });
  });
});
