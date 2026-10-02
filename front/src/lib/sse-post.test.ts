import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/api/client', () => ({
  buildUrl: (path: string) => `http://api.test${path}`,
  getAccessToken: vi.fn(() => 'expired'),
  newIdempotencyKey: vi.fn(() => 'key-1'),
  refreshAccessToken: vi.fn(async () => 'fresh'),
}));

import { refreshAccessToken } from '@/lib/api/client';

import { streamPost } from './sse-post';

function sse(body: string, status = 200): Response {
  return new Response(new TextEncoder().encode(body), {
    status,
    headers: { 'content-type': 'text/event-stream' },
  });
}

async function collect(generator: AsyncGenerator<unknown>) {
  const events = [];
  for await (const event of generator) events.push(event);
  return events;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe('streamPost', () => {
  it('refreshes an expired token once and replays the same request', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response('{"error":{"code":"AUTH_REQUIRED"}}', { status: 401 }))
      .mockResolvedValueOnce(sse('event: complete\ndata: {"ok":true}\n\n'));
    vi.stubGlobal('fetch', fetchMock);

    const events = await collect(streamPost('/v1/scripts/dep_1/blocking/turns', { message: 'x' }));

    expect(events).toEqual([{ event: 'complete', data: { ok: true } }]);
    expect(refreshAccessToken).toHaveBeenCalledTimes(1);
    const [first, second] = fetchMock.mock.calls.map((call) => call[1] as RequestInit);
    expect((first!.headers as Record<string, string>).authorization).toBe('Bearer expired');
    expect((second!.headers as Record<string, string>).authorization).toBe('Bearer fresh');
    // Same logical turn: the idempotency key does not change on the retry.
    expect((second!.headers as Record<string, string>)['idempotency-key']).toBe('key-1');
  });

  it('surfaces the 401 when the refresh fails too', async () => {
    vi.mocked(refreshAccessToken).mockResolvedValueOnce(null);
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('', { status: 401 })));
    await expect(collect(streamPost('/v1/x', {}))).rejects.toMatchObject({ status: 401 });
  });
});
