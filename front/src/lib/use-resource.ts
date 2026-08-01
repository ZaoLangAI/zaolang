'use client';

import { useEffect, useState } from 'react';

import { api } from '@/lib/api/client';

interface Loaded<T> {
  path: string;
  status: 'ready' | 'failed';
  data?: T;
}

export interface Resource<T> {
  status: 'idle' | 'loading' | 'ready' | 'failed';
  data?: T;
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
 */
export function useResource<T>(path: string | null): Resource<T> {
  const [loaded, setLoaded] = useState<Loaded<T> | null>(null);

  useEffect(() => {
    if (path === null) return;
    let cancelled = false;
    void api
      .get<T>(path)
      .then((data) => {
        if (!cancelled) setLoaded({ path, status: 'ready', data });
      })
      .catch(() => {
        if (!cancelled) setLoaded({ path, status: 'failed' });
      });
    return () => {
      cancelled = true;
    };
  }, [path]);

  if (path === null) return { status: 'idle' };
  if (loaded?.path !== path) return { status: 'loading' };
  return { status: loaded.status, data: loaded.data };
}
