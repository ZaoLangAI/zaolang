import { afterEach, describe, expect, it, vi } from 'vitest';

import { getAccessToken, setAccessToken } from '@/lib/api/client';

import { syncThemePreference } from './theme-sync';

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

function headersOf(call: unknown[]): Record<string, string> {
  return (call[1] as RequestInit).headers as Record<string, string>;
}

/** Lets the fire-and-forget request (and any refresh/retry) settle. */
async function settle() {
  await vi.waitFor(() => undefined);
  for (let i = 0; i < 10; i += 1) await Promise.resolve();
}

afterEach(() => {
  setAccessToken(null);
  vi.unstubAllGlobals();
});

describe('syncThemePreference', () => {
  it('sends the theme with the bearer token when signed in', async () => {
    const fetchMock = vi.fn().mockResolvedValue(json({}));
    vi.stubGlobal('fetch', fetchMock);
    setAccessToken('tok');

    syncThemePreference('light', '/discover');
    await settle();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toMatch(/\/v1\/auth\/me\/preferences$/);
    expect(init.method).toBe('PATCH');
    expect(init.body).toBe(JSON.stringify({ theme: 'light' }));
    expect(headersOf(fetchMock.mock.calls[0]!).authorization).toBe('Bearer tok');
  });

  it('skips the request when signed out', async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);

    syncThemePreference('dark', '/discover');
    await settle();

    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('never touches consumer auth on console routes', async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    setAccessToken('tok');

    syncThemePreference('dark', '/admin');
    syncThemePreference('dark', '/admin/users');
    await settle();

    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('still syncs on consumer pages whose path merely contains "admin"', async () => {
    const fetchMock = vi.fn().mockResolvedValue(json({}));
    vi.stubGlobal('fetch', fetchMock);
    setAccessToken('tok');

    syncThemePreference('dark', '/profile/admin');
    syncThemePreference('dark', '/administrators');
    await settle();

    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('refreshes an expired token once and retries', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(json({ error: { code: 'AUTH_REQUIRED' } }, 401))
      .mockResolvedValueOnce(json({ access_token: 'fresh' }))
      .mockResolvedValueOnce(json({}));
    vi.stubGlobal('fetch', fetchMock);
    setAccessToken('expired');

    syncThemePreference('system', '/discover');
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));

    expect(headersOf(fetchMock.mock.calls[0]!).authorization).toBe('Bearer expired');
    expect(fetchMock.mock.calls[1]![0]).toMatch(/\/v1\/auth\/refresh$/);
    expect(headersOf(fetchMock.mock.calls[2]!).authorization).toBe('Bearer fresh');
    expect(getAccessToken()).toBe('fresh');
  });

  it('swallows a failed write', async () => {
    const fetchMock = vi.fn().mockRejectedValue(new TypeError('network down'));
    vi.stubGlobal('fetch', fetchMock);
    setAccessToken('tok');

    expect(() => syncThemePreference('dark', '/discover')).not.toThrow();
    await settle();

    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
