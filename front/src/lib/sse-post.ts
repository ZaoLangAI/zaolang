import { buildUrl, getAccessToken, newIdempotencyKey, refreshAccessToken } from '@/lib/api/client';
import { ApiError, type ApiErrorBody } from '@/lib/api/errors';

export type AgentSseEvent = {
  event: string;
  data: Record<string, unknown>;
};

/**
 * POST-initiated SSE: one request/response, no Last-Event-ID resume.
 * Same envelope as script-writing turns (`thinking` / `delta` / `complete` / `error`).
 */
export async function* streamPost(
  path: string,
  body: unknown,
  signal?: AbortSignal,
  options?: { getToken?: () => string | null | Promise<string | null> },
): AsyncGenerator<AgentSseEvent> {
  const token = options?.getToken
    ? await options.getToken()
    : (getAccessToken() ?? (await refreshAccessToken()));
  // One key for the logical request, so the retry below is recognised as
  // the same turn rather than a second one.
  const idempotencyKey = newIdempotencyKey();
  const open = (bearer: string | null) =>
    fetch(buildUrl(path), {
      method: 'POST',
      headers: {
        accept: 'text/event-stream',
        'content-type': 'application/json',
        'idempotency-key': idempotencyKey,
        ...(bearer ? { authorization: `Bearer ${bearer}` } : {}),
      },
      credentials: 'include',
      body: JSON.stringify(body),
      signal,
    });
  let response = await open(token);
  // An access token that expired while the page sat open is routine, not a
  // logout — same single refresh-and-retry `apiRequest` does. A 401 always
  // arrives before any event is streamed, so retrying cannot duplicate one.
  if (response.status === 401 && !options?.getToken) {
    const fresh = await refreshAccessToken();
    if (fresh) response = await open(fresh);
  }
  if (!response.ok || !response.body) {
    const text = await response.text().catch(() => '');
    let parsed: ApiErrorBody | undefined;
    try {
      parsed = text ? (JSON.parse(text) as ApiErrorBody) : undefined;
    } catch {
      parsed = undefined;
    }
    throw new ApiError(response.status, parsed, response.statusText || `HTTP ${response.status}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const frames = buffer.split('\n\n');
    buffer = frames.pop() ?? '';
    for (const frame of frames) {
      const parsed = parseSseFrame(frame);
      if (parsed) yield parsed;
    }
  }
}

export function parseSseFrame(frame: string): AgentSseEvent | null {
  let event = 'message';
  let data = '';
  for (const line of frame.split('\n')) {
    if (line.startsWith('event:')) event = line.slice('event:'.length).trim();
    else if (line.startsWith('data:')) data += line.slice('data:'.length).trim();
  }
  if (!data) return null;
  try {
    return { event, data: JSON.parse(data) as Record<string, unknown> };
  } catch {
    return null;
  }
}
