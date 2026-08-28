'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

import { api } from '@/lib/api/client';
import { dedupedFetch, getCached, setCached } from '@/lib/resource-cache';

interface Loaded<T> {
  path: string;
  status: 'ready' | 'failed';
  data?: T;
}

export interface Resource<T> {
  status: 'idle' | 'loading' | 'ready' | 'failed';
  data?: T;
  /** Re-runs the fetch for the current path. No-op while `path` is null. */
  refetch: () => void;
}

/** `loaded` plus the `path` it was seeded for, so a path change is a plain
 *  state comparison rather than a ref read (refs can't be read during render). */
interface Seeded<T> {
  path: string | null;
  loaded: Loaded<T> | null;
}

function seed<T>(path: string | null): Seeded<T> {
  if (path === null) return { path, loaded: null };
  const cached = getCached<T>(path);
  return { path, loaded: cached === undefined ? null : { path, status: 'ready', data: cached } };
}

/**
 * GETs one API path on demand, or nothing while the path is null.
 *
 * The path is stored *with* the result, so "loading" is derived from a path
 * that has not resolved yet rather than from a state reset at the top of the
 * effect. That keeps a path change from costing an extra render pass, and makes
 * a late response for a previous path impossible to display.
 *
 * Takes a path rather than a loader function because every caller is a plain
 * authenticated GET, and a function argument would have to be memoised by each
 * of them to avoid refetching on every render.
 *
 * Every mount still fires the same request it always did — nothing here skips
 * a fetch. Two things change: a path already seen elsewhere in this session
 * paints its last known data immediately (`seedFromCache`) instead of a loading
 * state while that fetch is in flight (stale-while-revalidate, resolved by the
 * effect below writing the fresh result over it), and two components asking
 * for the same path at once (`dedupedFetch`, `resource-cache.ts`) share one
 * network request instead of firing two.
 */
export function useResource<T>(path: string | null): Resource<T> {
  const [stored, setStored] = useState<Seeded<T>>(() => seed<T>(path));
  const [gen, setGen] = useState(0);
  const [pending, setPending] = useState(false);
  // Only a genuine `refetch()` call sets this — a path change or the
  // initial mount's own automatic fetch must never flip `pending`, or the
  // hook's stale-while-revalidate silence (a cached path staying `ready`
  // while it quietly refreshes) would regress into a `loading` flash for
  // every one of this hook's existing callers.
  const manualRefetchRef = useRef(false);
  const refetch = useCallback(() => {
    manualRefetchRef.current = true;
    setGen((g) => g + 1);
  }, []);

  // A later path change has to re-seed from the cache the same way the
  // initial render does, or a path swap would show a loading state even when
  // the new path's data is already known. Comparing against `stored.path`
  // (plain state, not a ref — refs can't be read during render) and calling
  // `setStored` here is React's documented "adjust state during rendering"
  // pattern for resetting state on a prop change, chosen over an effect
  // specifically to avoid the one-frame loading flash an effect-based reset
  // would cost. `state` (below) uses the freshly seeded value immediately,
  // rather than the stale `stored` this render started with, so this
  // render's own return value is already correct — not just the next one's.
  const state = stored.path === path ? stored : seed<T>(path);
  if (stored.path !== path) setStored(state);

  useEffect(() => {
    if (path === null) return;
    let cancelled = false;
    const isManualRefetch = manualRefetchRef.current;
    manualRefetchRef.current = false;
    if (isManualRefetch) setPending(true);
    void dedupedFetch(path, () => api.get<T>(path))
      .then((data) => {
        setCached(path, data);
        if (!cancelled) {
          setStored({ path, loaded: { path, status: 'ready', data } });
          if (isManualRefetch) setPending(false);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setStored({ path, loaded: { path, status: 'failed' } });
          if (isManualRefetch) setPending(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [path, gen]);

  if (path === null) return { status: 'idle', refetch };
  // A manual retry keeps showing whatever was last known (if anything) while
  // the refetch is in flight, rather than blanking to a bare loading state —
  // only the very first fetch for a path does that.
  if (pending && state.loaded?.path === path) {
    return { status: 'loading', data: state.loaded.data, refetch };
  }
  if (state.loaded?.path !== path) return { status: 'loading', refetch };
  return { status: state.loaded.status, data: state.loaded.data, refetch };
}
