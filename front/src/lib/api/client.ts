import { ApiError, type ApiErrorBody } from '@/lib/api/errors';

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

/**
 * The access token is held in memory only.
 *
 * Putting it in `localStorage` would make every XSS a permanent account
 * takeover; the long-lived half of the session is the httpOnly refresh cookie,
 * which JavaScript cannot read. A reload therefore starts with no token and
 * silently re-derives one from the cookie.
 */
let accessToken: string | null = null;
let refreshInFlight: Promise<string | null> | null = null;

const listeners = new Set<(token: string | null) => void>();

export function getAccessToken(): string | null {
  return accessToken;
}

export function setAccessToken(token: string | null): void {
  accessToken = token;
  for (const listener of listeners) listener(token);
}

export function onAccessTokenChange(listener: (token: string | null) => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  body?: unknown;
  query?: Record<string, string | number | boolean | undefined | null>;
  /** Sent as `Idempotency-Key`; required by the API for credit-moving calls. */
  idempotencyKey?: string;
  signal?: AbortSignal;
  /** Skip the refresh-and-retry dance, used by the auth calls themselves. */
  anonymous?: boolean;
  headers?: Record<string, string>;
}

export function buildUrl(path: string, query?: RequestOptions['query']): string {
  const url = new URL(path.startsWith('http') ? path : `${API_URL}${path}`);
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined && value !== null && value !== '') {
      url.searchParams.set(key, String(value));
    }
  }
  return url.toString();
}

/**
 * Exchanges the refresh cookie for a new access token.
 *
 * Single-flight: a page that fires five requests at once after a reload must
 * not send five refreshes, because each one rotates the cookie and the losers
 * would end up holding a token derived from a cookie that no longer exists.
 */
export async function refreshAccessToken(): Promise<string | null> {
  refreshInFlight ??= (async () => {
    try {
      const response = await fetch(buildUrl('/v1/auth/refresh'), {
        method: 'POST',
        credentials: 'include',
      });
      if (!response.ok) {
        setAccessToken(null);
        return null;
      }
      const body = (await response.json()) as { access_token: string };
      setAccessToken(body.access_token);
      return body.access_token;
    } catch {
      setAccessToken(null);
      return null;
    } finally {
      refreshInFlight = null;
    }
  })();
  return refreshInFlight;
}

async function send(
  path: string,
  options: RequestOptions,
  token: string | null,
): Promise<Response> {
  const headers: Record<string, string> = { accept: 'application/json', ...options.headers };
  if (options.body !== undefined) headers['content-type'] = 'application/json';
  if (options.idempotencyKey) headers['idempotency-key'] = options.idempotencyKey;
  if (token) headers.authorization = `Bearer ${token}`;

  return fetch(buildUrl(path, options.query), {
    method: options.method ?? 'GET',
    headers,
    credentials: 'include',
    signal: options.signal,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  });
}

export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  let response = await send(path, options, options.anonymous ? null : accessToken);

  // A 401 on a page that was open across a token expiry is routine, not a
  // logout: try once with a fresh token before surfacing it to the user.
  if (response.status === 401 && !options.anonymous) {
    const token = await refreshAccessToken();
    if (token) response = await send(path, options, token);
  }

  if (response.status === 204) return undefined as T;

  const text = await response.text();
  const payload = text ? (JSON.parse(text) as unknown) : undefined;

  if (!response.ok) {
    throw new ApiError(response.status, payload as ApiErrorBody | undefined, response.statusText);
  }
  return payload as T;
}

export const api = {
  get: <T>(path: string, options?: Omit<RequestOptions, 'method' | 'body'>) =>
    apiRequest<T>(path, { ...options, method: 'GET' }),
  post: <T>(path: string, body?: unknown, options?: Omit<RequestOptions, 'method' | 'body'>) =>
    apiRequest<T>(path, { ...options, method: 'POST', body }),
  put: <T>(path: string, body?: unknown, options?: Omit<RequestOptions, 'method' | 'body'>) =>
    apiRequest<T>(path, { ...options, method: 'PUT', body }),
  patch: <T>(path: string, body?: unknown, options?: Omit<RequestOptions, 'method' | 'body'>) =>
    apiRequest<T>(path, { ...options, method: 'PATCH', body }),
  delete: <T>(path: string, options?: Omit<RequestOptions, 'method' | 'body'>) =>
    apiRequest<T>(path, { ...options, method: 'DELETE' }),
};

/** Idempotency keys must be stable per user intent, not per retry. */
export function newIdempotencyKey(): string {
  return globalThis.crypto.randomUUID();
}
