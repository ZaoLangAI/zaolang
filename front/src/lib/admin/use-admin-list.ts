'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';

import { adminApi } from '@/lib/api/admin-client';
import type { Page } from '@/lib/api/admin-types';

export interface AdminList<T> {
  rows: T[];
  loading: boolean;
  failed: boolean;
  filters: Record<string, string>;
  setFilter: (id: string, value: string) => void;
  resetFilters: () => void;
  hasPrev: boolean;
  hasNext: boolean;
  nextPage: () => void;
  prevPage: () => void;
  reload: () => void;
}

/**
 * Filtered, cursor-paged list backing every console table.
 *
 * Cursors rather than offsets: these lists are written to while being read, and
 * an offset silently skips or repeats rows when something is inserted above the
 * current page. Going back keeps a stack of the cursors already visited, because
 * a cursor only knows how to move forward.
 */
export function useAdminList<T>(
  path: string,
  options: { pageSize?: number; initialFilters?: Record<string, string> } = {},
): AdminList<T> {
  const pageSize = options.pageSize ?? 50;
  const initialFilters = useMemo(() => options.initialFilters ?? {}, [options.initialFilters]);

  const [filters, setFilters] = useState<Record<string, string>>(initialFilters);
  const [cursors, setCursors] = useState<Array<string | null>>([null]);
  const [reloadToken, setReloadToken] = useState(0);
  const [result, setResult] = useState<{
    key: string;
    rows: T[];
    hasNext: boolean;
    nextCursor: string | null;
    failed: boolean;
  } | null>(null);

  const cursor = cursors[cursors.length - 1];
  const filterKey = JSON.stringify(filters);
  // The request identity. Loading is "what is on screen does not match what was
  // asked for", which avoids flipping a loading flag from inside the effect.
  const requestKey = `${path}|${filterKey}|${cursor ?? ''}|${pageSize}|${reloadToken}`;

  useEffect(() => {
    let cancelled = false;
    void adminApi
      .get<Page<T>>(path, {
        query: { ...JSON.parse(filterKey), cursor: cursor ?? undefined, limit: pageSize },
      })
      .then((body) => {
        if (cancelled) return;
        setResult({
          key: requestKey,
          rows: body.items,
          hasNext: Boolean(body.has_more),
          nextCursor: body.next_cursor ?? null,
          failed: false,
        });
      })
      .catch(() => {
        if (cancelled) return;
        setResult({ key: requestKey, rows: [], hasNext: false, nextCursor: null, failed: true });
      });
    return () => {
      cancelled = true;
    };
  }, [path, filterKey, cursor, pageSize, requestKey]);

  const setFilter = useCallback((id: string, value: string) => {
    // Any filter change invalidates the cursor stack: page 3 of the old query
    // has no meaning in the new one.
    setCursors([null]);
    setFilters((current) => ({ ...current, [id]: value }));
  }, []);

  const resetFilters = useCallback(() => {
    setCursors([null]);
    setFilters(initialFilters);
  }, [initialFilters]);

  const fresh = result?.key === requestKey ? result : null;

  return {
    rows: fresh?.rows ?? [],
    loading: fresh === null,
    failed: fresh?.failed ?? false,
    filters,
    setFilter,
    resetFilters,
    hasPrev: cursors.length > 1,
    hasNext: fresh?.hasNext ?? false,
    nextPage: () => {
      const next = fresh?.nextCursor;
      if (next) setCursors((stack) => [...stack, next]);
    },
    prevPage: () => setCursors((stack) => (stack.length > 1 ? stack.slice(0, -1) : stack)),
    reload: () => setReloadToken((token) => token + 1),
  };
}
