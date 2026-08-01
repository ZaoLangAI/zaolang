import 'server-only';

import { cookies } from 'next/headers';

import { ApiError, type ApiErrorBody } from '@/lib/api/errors';

const INTERNAL_URL = process.env.API_INTERNAL_URL ?? 'http://localhost:8000';

/**
 * The console session cookie.
 *
 * A separate name and a separate signing secret from `zl_refresh`: signing in
 * to the consumer site must never grant console access, so the two sessions
 * cannot share a credential.
 */
export const ADMIN_COOKIE = 'zl_admin_session';

interface AdminRequestOptions {
  query?: Record<string, string | number | boolean | undefined | null>;
}

/**
 * Reads an admin endpoint during a server render.
 *
 * Console data is never cached: it is per-operator, it is the basis for
 * privileged decisions, and a stale queue is worse than a slow one.
 */
export async function adminFetch<T>(path: string, options: AdminRequestOptions = {}): Promise<T> {
  const jar = await cookies();
  const session = jar.get(ADMIN_COOKIE);

  const url = new URL(`${INTERNAL_URL}${path}`);
  for (const [key, value] of Object.entries(options.query ?? {})) {
    if (value !== undefined && value !== null && value !== '') {
      url.searchParams.set(key, String(value));
    }
  }

  const response = await fetch(url, {
    headers: {
      accept: 'application/json',
      // The admin token is the cookie value itself; there is no refresh
      // exchange, because a console session is short-lived on purpose.
      ...(session
        ? { authorization: `Bearer ${session.value}`, cookie: `${ADMIN_COOKIE}=${session.value}` }
        : {}),
    },
    cache: 'no-store',
  });

  const text = await response.text();
  const payload = text ? (JSON.parse(text) as unknown) : undefined;

  if (!response.ok) {
    throw new ApiError(response.status, payload as ApiErrorBody | undefined, response.statusText);
  }
  return payload as T;
}

export async function adminFetchOrNull<T>(
  path: string,
  options: AdminRequestOptions = {},
): Promise<T | null> {
  try {
    return await adminFetch<T>(path, options);
  } catch (error) {
    if (
      error instanceof ApiError &&
      (error.isNotFound || error.isAuthRequired || error.isForbidden)
    ) {
      return null;
    }
    throw error;
  }
}

export async function hasAdminSession(): Promise<boolean> {
  return (await cookies()).has(ADMIN_COOKIE);
}
