import 'server-only';

import { cookies } from 'next/headers';
import { redirect } from 'next/navigation';
import { getLocale } from 'next-intl/server';

import { ApiError, type ApiErrorBody } from '@/lib/api/errors';

const INTERNAL_URL = process.env.API_INTERNAL_URL ?? 'http://localhost:3001';

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
 * The raw console request. Callers decide whether a 401 is "no session yet"
 * (`adminFetchOrNull` on the login page) or "send the operator back to login"
 * (`adminFetch` on every protected render).
 */
async function adminRequest<T>(path: string, options: AdminRequestOptions = {}): Promise<T> {
  const jar = await cookies();
  const session = jar.get(ADMIN_COOKIE);

  const url = new URL(`${INTERNAL_URL}${path}`);
  for (const [key, value] of Object.entries(options.query ?? {})) {
    if (value !== undefined && value !== null && value !== '') {
      url.searchParams.set(key, String(value));
    }
  }

  let response: Response;
  try {
    response = await fetch(url, {
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
  } catch {
    throw new ApiError(503, undefined, 'API unreachable');
  }

  const text = await response.text();
  let payload: unknown;
  try {
    payload = text ? (JSON.parse(text) as unknown) : undefined;
  } catch {
    payload = undefined;
  }

  if (!response.ok) {
    throw new ApiError(response.status, payload as ApiErrorBody | undefined, response.statusText);
  }
  return payload as T;
}

/**
 * Reads an admin endpoint during a server render.
 *
 * Console data is never cached: it is per-operator, it is the basis for
 * privileged decisions, and a stale queue is worse than a slow one.
 *
 * A 401 here means the cookie is gone or the JWT has expired. Layout and page
 * render in parallel, so throwing would surface as a Runtime ApiError overlay
 * and race the layout's own redirect; send the operator to the console login
 * instead.
 */
export async function adminFetch<T>(path: string, options: AdminRequestOptions = {}): Promise<T> {
  try {
    return await adminRequest<T>(path, options);
  } catch (error) {
    if (!(error instanceof ApiError && error.isAuthRequired)) throw error;
  }
  const locale = await getLocale();
  redirect(`/${locale}/admin/login`);
}

export async function adminFetchOrNull<T>(
  path: string,
  options: AdminRequestOptions = {},
): Promise<T | null> {
  try {
    return await adminRequest<T>(path, options);
  } catch (error) {
    if (
      error instanceof ApiError &&
      (error.isNotFound || error.isAuthRequired || error.isForbidden || error.isUnavailable)
    ) {
      return null;
    }
    throw error;
  }
}

export async function hasAdminSession(): Promise<boolean> {
  return (await cookies()).has(ADMIN_COOKIE);
}
