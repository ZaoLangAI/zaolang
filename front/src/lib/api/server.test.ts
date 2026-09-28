import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const cookieJar = new Map<string, string>();
vi.mock('next/headers', () => ({
  cookies: async () => ({
    get: (name: string) => (cookieJar.has(name) ? { value: cookieJar.get(name) } : undefined),
    has: (name: string) => cookieJar.has(name),
  }),
}));

import { serverFetch, serverFetchOrNull } from '@/lib/api/server';

type FetchInit = RequestInit & { next?: { revalidate?: number | false; tags?: string[] } };

const fetchMock = vi.fn<(url: string, init?: FetchInit) => Promise<Response>>();

function initFor(path: string): FetchInit {
  const call = fetchMock.mock.calls.find(([url]) => new URL(url).pathname === path);
  if (!call) throw new Error(`no fetch to ${path}`);
  return call[1] ?? {};
}

beforeEach(() => {
  cookieJar.clear();
  fetchMock.mockReset();
  fetchMock.mockImplementation(async (url) =>
    new URL(url).pathname === '/v1/auth/refresh'
      ? Response.json({ access_token: 'token' })
      : Response.json({ items: [] }),
  );
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

// Public payloads carry presigned media URLs that expire 15 minutes after the
// API mints them, and Next's data cache hands out stale entries of any age.
describe('public server reads stay out of the data cache', () => {
  it('does not cache a public read by default', async () => {
    await serverFetch('/v1/works');

    const init = initFor('/v1/works');
    expect(init.cache).toBe('no-store');
    expect(init.next).toBeUndefined();
  });

  it('does not cache through serverFetchOrNull either', async () => {
    await serverFetchOrNull('/v1/works/wrk_1');

    const init = initFor('/v1/works/wrk_1');
    expect(init.cache).toBe('no-store');
    expect(init.next).toBeUndefined();
  });

  it('caches a public read only when the caller opts in', async () => {
    await serverFetch('/v1/tags', { revalidate: 300 });

    const init = initFor('/v1/tags');
    expect(init.cache).toBeUndefined();
    expect(init.next).toEqual({ revalidate: 300, tags: undefined });
  });

  it('never caches an authenticated read, even when asked to', async () => {
    cookieJar.set('zl_refresh', 'refresh');

    await serverFetch('/v1/me/bookmarks', { authenticated: true, revalidate: 300 });

    const init = initFor('/v1/me/bookmarks');
    expect(init.cache).toBe('no-store');
    expect(init.next).toBeUndefined();
    expect(new Headers(init.headers).get('authorization')).toBe('Bearer token');
  });
});
