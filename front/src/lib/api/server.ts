import 'server-only';

import { cookies } from 'next/headers';

import { ApiError, type ApiErrorBody } from '@/lib/api/errors';

/**
 * Server components talk to the API over the internal address.
 *
 * In a container deployment the browser-visible host is not reachable from the
 * server, so the two URLs are configured separately rather than derived.
 */
const INTERNAL_URL = process.env.API_INTERNAL_URL ?? 'http://localhost:8000';

export const REFRESH_COOKIE = 'zl_refresh';

interface ServerRequestOptions {
  query?: Record<string, string | number | boolean | undefined | null>;
  /** Attach the caller's session. Omit for public data so it stays cacheable. */
  authenticated?: boolean;
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

  const response = await fetch(`${INTERNAL_URL}/v1/auth/refresh`, {
    method: 'POST',
    headers: { cookie: `${REFRESH_COOKIE}=${refresh.value}` },
    cache: 'no-store',
  });
  if (!response.ok) return null;
  const body = (await response.json()) as { access_token: string };
  return body.access_token;
}

export async function serverFetch<T>(path: string, options: ServerRequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = { accept: 'application/json' };
  if (options.authenticated) {
    const token = await accessTokenFromCookie();
    if (token) headers.authorization = `Bearer ${token}`;
  }

  const response = await fetch(buildUrl(path, options.query), {
    headers,
    // Authenticated reads are per-user and must never land in a shared cache.
    cache: options.authenticated ? 'no-store' : undefined,
    next: options.authenticated
      ? undefined
      : { revalidate: options.revalidate ?? 30, tags: options.tags },
  });

  const text = await response.text();
  const payload = text ? (JSON.parse(text) as unknown) : undefined;

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
    if (error instanceof ApiError && (error.isNotFound || error.isAuthRequired)) return null;
    throw error;
  }
}

export async function isSignedIn(): Promise<boolean> {
  const jar = await cookies();
  return jar.has(REFRESH_COOKIE);
}
