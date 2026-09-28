import 'server-only';

import { cookies } from 'next/headers';

import { ApiError, type ApiErrorBody } from '@/lib/api/errors';

/**
 * Server components talk to the API over the internal address.
 *
 * In a container deployment the browser-visible host is not reachable from the
 * server, so the two URLs are configured separately rather than derived.
 */
const INTERNAL_URL = process.env.API_INTERNAL_URL ?? 'http://localhost:3001';

export const REFRESH_COOKIE = 'zl_refresh';

interface ServerRequestOptions {
  query?: Record<string, string | number | boolean | undefined | null>;
  /** Attach the caller's session. Authenticated reads are never cached. */
  authenticated?: boolean;
  /**
   * Opt a public read into Next's data cache. Uncached unless set.
   *
   * Only for payloads that carry no presigned media URL (`/v1/tags`, not
   * `/v1/works`). The data cache is stale-while-revalidate with no bound on
   * staleness: the first render after a quiet spell gets the cached payload
   * however old it is, and a URL signed for 15 minutes (the API's
   * `download_url_ttl_seconds`) is then long expired — `/_next/image` gets a
   * 403 and the cover breaks. No revalidate value is short enough to prevent
   * that, since the gap is set by traffic, not by this number.
   */
  revalidate?: number | false;
  tags?: string[];
}

function buildUrl(path: string, query: ServerRequestOptions['query']): string {
  const url = new URL(`${INTERNAL_URL}${path}`);
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined && value !== null && value !== '') {
      url.searchParams.set(key, String(value));
    }
  }
  return url.toString();
}

/**
 * Turns the refresh cookie into a short-lived access token.
 *
 * The server has no access token of its own — the browser keeps that in
 * memory — so an authenticated render starts by redeeming the cookie.
 */
async function accessTokenFromCookie(): Promise<string | null> {
  const jar = await cookies();
  const refresh = jar.get(REFRESH_COOKIE);
  if (!refresh) return null;

  let response: Response;
  try {
    response = await fetch(`${INTERNAL_URL}/v1/auth/refresh`, {
      method: 'POST',
      headers: { cookie: `${REFRESH_COOKIE}=${refresh.value}` },
      cache: 'no-store',
    });
  } catch {
    return null;
  }
  if (!response.ok) return null;
  const body = (await readJson(response)) as { access_token?: string } | undefined;
  return body?.access_token ?? null;
}

async function readJson(response: Response): Promise<unknown> {
  const text = await response.text();
  if (!text) return undefined;
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return undefined;
  }
}

export async function serverFetch<T>(path: string, options: ServerRequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = { accept: 'application/json' };
  if (options.authenticated) {
    const token = await accessTokenFromCookie();
    if (token) headers.authorization = `Bearer ${token}`;
  }

  // Authenticated reads are per-user and must never land in a shared cache;
  // public ones only when the caller vouches the payload holds no signed URL.
  const cached = !options.authenticated && options.revalidate !== undefined;

  let response: Response;
  try {
    response = await fetch(buildUrl(path, options.query), {
      headers,
      cache: cached ? undefined : 'no-store',
      next: cached ? { revalidate: options.revalidate, tags: options.tags } : undefined,
    });
  } catch {
    throw new ApiError(503, undefined, 'API unreachable');
  }

  const payload = await readJson(response);

  if (!response.ok) {
    throw new ApiError(response.status, payload as ApiErrorBody | undefined, response.statusText);
  }
  return payload as T;
}

/** Reads that are allowed to come back empty, e.g. an optional side panel. */
export async function serverFetchOrNull<T>(
  path: string,
  options: ServerRequestOptions = {},
): Promise<T | null> {
  try {
    return await serverFetch<T>(path, options);
  } catch (error) {
    if (
      error instanceof ApiError &&
      (error.isNotFound || error.isAuthRequired || error.isUnavailable)
    ) {
      return null;
    }
    throw error;
  }
}

export async function isSignedIn(): Promise<boolean> {
  const jar = await cookies();
  return jar.has(REFRESH_COOKIE);
}
