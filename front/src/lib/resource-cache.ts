/**
 * Pure, React-free cache backing `useResource` (see `use-resource.ts`).
 *
 * Two independent jobs:
 *  - `dedupedFetch` coalesces concurrent callers of the same path into one
 *    in-flight request — two components mounting at once and asking for the
 *    same GET must not fire it twice.
 *  - `getCached`/`setCached` remember the last successful response per path
 *    so a remount can paint instantly (stale-while-revalidate) instead of
 *    showing a loading skeleton while a request that will very likely return
 *    the same data is still in flight.
 *
 * Deliberately has no TTL and never skips a fetch on its own: every mount
 * still triggers exactly the same network request it would without this
 * module. This file only changes what is available to paint *before* that
 * request resolves and how many requests concurrent callers produce — not
 * whether a request happens.
 */

interface CacheEntry {
  data: unknown;
  updatedAt: number;
}

const cache = new Map<string, CacheEntry>();
const inflight = new Map<string, Promise<unknown>>();

export function getCached<T>(path: string): T | undefined {
  return cache.get(path)?.data as T | undefined;
}

export function setCached<T>(path: string, data: T): void {
  cache.set(path, { data, updatedAt: Date.now() });
}

/**
 * Runs `loader` for `path`, sharing one promise across concurrent callers.
 *
 * The in-flight entry is cleared as soon as the promise settles (success or
 * failure) so the *next* call — not a queued one, a genuinely later one —
 * always starts a fresh request rather than replaying a stale rejection.
 */
export function dedupedFetch<T>(path: string, loader: () => Promise<T>): Promise<T> {
  const existing = inflight.get(path);
  if (existing) return existing as Promise<T>;

  const promise = loader().finally(() => {
    inflight.delete(path);
  });
  inflight.set(path, promise);
  return promise;
}

/** Drops one path's cached value, e.g. after a mutation that invalidates it. */
export function invalidateResource(path: string): void {
  cache.delete(path);
}

/** Drops every cached path for which `predicate` is true. */
export function invalidateResourceMatching(predicate: (path: string) => boolean): void {
  for (const path of cache.keys()) {
    if (predicate(path)) cache.delete(path);
  }
}

/** Test-only: resets both maps so cases don't leak state into each other. */
export function clearResourceCache(): void {
  cache.clear();
  inflight.clear();
}
