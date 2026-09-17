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
  const response = await fetch(buildUrl(path), {
    method: 'POST',
    headers: {
      accept: 'text/event-stream',
      'content-type': 'application/json',
      'idempotency-key': newIdempotencyKey(),
      ...(token ? { authorization: `Bearer ${token}` } : {}),
    },
    credentials: 'include',
    body: JSON.stringify(body),
    signal,
  });
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
