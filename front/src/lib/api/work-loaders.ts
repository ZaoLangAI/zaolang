import 'server-only';

import { cache } from 'react';

import { serverFetchOrNull } from '@/lib/api/server';
import type { WorkDetail } from '@/lib/api/types';

/**
 * Deduplicates work fetches within a single RSC request so
 * `generateMetadata` and the page body share one network round-trip.
 */
export const getWork = cache(async (workId: string, authenticated = false) => {
  return serverFetchOrNull<WorkDetail>(
    `/v1/works/${workId}`,
    authenticated ? { authenticated: true } : {},
  );
});
