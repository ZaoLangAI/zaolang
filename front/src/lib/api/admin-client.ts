'use client';

import { API_URL, type RequestOptions } from '@/lib/api/client';
import { ApiError, type ApiErrorBody } from '@/lib/api/errors';

/**
 * Console API client, deliberately separate from the consumer one.
 *
 * It shares no token store with `lib/api/client`, and it never retries on 401.
 * A console session that has expired must land the operator back on the console
 * login page, not silently continue with a consumer credential.
 *
 * The session itself is entirely the httpOnly `zl_admin_session` cookie,
 * always sent via `credentials: 'include'` below (`get_admin_user` only
 * falls back to a bearer header for non-browser tooling). This in-memory
 * slot exists only for the couple of SSE call sites that pass a bearer
 * header explicitly (`use-admin-job-stream.ts`, the agent debug chat) —
 * nothing sets it anymore (`AdminSessionResponse` has no `access_token` to
 * feed it; see `AdminSessionProvider`'s own note), so it now always reads
 * back `null` and those call sites fall through to the cookie alone, same
 * as every other console request.
 */
let adminToken: string | null = null;

const ADMIN_LOGIN_PATH = '/v1/admin/auth/login';

export function setAdminToken(token: string | null): void {
  adminToken = token;
}

export function getAdminToken(): string | null {
  return adminToken;
}

/** Full navigation so the console layout re-reads the cookie from scratch. */
function redirectToAdminLogin(): void {
  setAdminToken(null);
  window.location.assign(`${window.location.pathname.split('/admin')[0]}/admin/login`);
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = { accept: 'application/json', ...options.headers };
  if (options.body !== undefined) headers['content-type'] = 'application/json';
  if (options.idempotencyKey) headers['idempotency-key'] = options.idempotencyKey;
  if (adminToken) headers.authorization = `Bearer ${adminToken}`;

  const url = new URL(`${API_URL}${path}`);
  for (const [key, value] of Object.entries(options.query ?? {})) {
    if (value !== undefined && value !== null && value !== '') {
      url.searchParams.set(key, String(value));
    }
  }

  const response = await fetch(url, {
    method: options.method ?? 'GET',
    headers,
    credentials: 'include',
    signal: options.signal,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  });

  if (response.status === 204) return undefined as T;

  const text = await response.text();
  const payload = text ? (JSON.parse(text) as unknown) : undefined;

  if (!response.ok) {
    const error = new ApiError(
      response.status,
      payload as ApiErrorBody | undefined,
      response.statusText,
    );
    // Wrong password is also 401; kicking the login form would hide the error.
    if (error.isAuthRequired && path !== ADMIN_LOGIN_PATH) {
      redirectToAdminLogin();
    }
    throw error;
  }
  return payload as T;
}

export const adminApi = {
  get: <T>(path: string, options?: Omit<RequestOptions, 'method' | 'body'>) =>
    request<T>(path, { ...options, method: 'GET' }),
  post: <T>(path: string, body?: unknown, options?: Omit<RequestOptions, 'method' | 'body'>) =>
    request<T>(path, { ...options, method: 'POST', body }),
  put: <T>(path: string, body?: unknown, options?: Omit<RequestOptions, 'method' | 'body'>) =>
    request<T>(path, { ...options, method: 'PUT', body }),
  patch: <T>(path: string, body?: unknown, options?: Omit<RequestOptions, 'method' | 'body'>) =>
    request<T>(path, { ...options, method: 'PATCH', body }),
  delete: <T>(path: string, options?: Omit<RequestOptions, 'method' | 'body'>) =>
    request<T>(path, { ...options, method: 'DELETE' }),
};
